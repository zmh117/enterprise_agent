from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

try:
    from mcp.server.mcpserver.exceptions import ToolError
except ModuleNotFoundError:  # MCP 1.x is used only by Worker-side contract tests.
    from mcp.server.fastmcp.exceptions import ToolError

from services.mcp_common import AuthorizedToolContext
from services.mcp_common.platform_store import PlatformRuntimeStore
from services.mcp_common.provenance import McpProvenanceRecorder
from services.mcp_common.sensitive_data import sanitize_sensitive_data
from services.mcp_common.secret_crypto import ProviderTokenDecryptor
from services.ones_mcp_server.contracts import (
    SERVER_CODE,
    SERVER_VERSION,
    OnesWorkItem,
    OnesWorkItemSearchResult,
)


_SEARCH_PATH = "/project/api/project/items/graphql"
_SEARCH_DOCUMENT = """
query SearchWorkItems($keyword: String!, $issue_type: String!, $limit: Int!, $user_id: ID!, $team_id: ID!) {
  workItems(keyword: $keyword, issueType: $issue_type, limit: $limit, userId: $user_id, teamId: $team_id) {
    items { number name type }
    total
    truncated
  }
}
""".strip()


@dataclass(frozen=True, slots=True)
class OnesCallCredential:
    credential_id: str
    credential_revision: int
    token: str
    base_url: str
    allowed_hosts: tuple[str, ...]
    external_user_id: str
    default_team_id: str


@dataclass(frozen=True, slots=True)
class ResolvedOnesCall:
    authorized: AuthorizedToolContext
    credential: OnesCallCredential


class OnesRuntimeResolver:
    def __init__(
        self,
        store: PlatformRuntimeStore,
        decryptor: ProviderTokenDecryptor,
        *,
        environment: str,
        allow_insecure_local: bool = False,
    ) -> None:
        self.store = store
        self.decryptor = decryptor
        self.environment = environment.lower()
        self.allow_insecure_local = allow_insecure_local

    def resolve(self, context: AuthorizedToolContext) -> OnesCallCredential:
        snapshot = context.job.subject
        row = self.store.query.execute_one(
            """
            select u.status as user_status,
                   i.id as identity_id, i.user_id as identity_user_id,
                   i.external_subject_id, i.provider_instance_id,
                   i.metadata_json, i.status as identity_status,
                   i.binding_revision,
                   p.base_url, p.allowed_hosts_json, p.status as provider_status,
                   c.id as credential_id, c.revision as credential_revision,
                   c.token_ciphertext, c.encryption_key_id,
                   c.status as credential_status
              from app_user u
              join user_external_identity i on i.id = ? and i.user_id = u.id
              join provider_instance p on p.id = i.provider_instance_id
              join provider_credential c on c.id = (
                    select c2.id from provider_credential c2
                     where c2.user_id = u.id
                       and c2.external_identity_id = i.id
                       and c2.provider_instance_id = p.id
                       and c2.status = 'ACTIVE'
                     order by c2.revision desc limit 1
              )
             where u.id = ?
            """,
            (snapshot.external_identity_id, context.job.app_user_id),
        )
        if row is None:
            raise ToolError("ONES verification is required")
        metadata = _object(row.get("metadata_json"))
        if any(
            (
                str(row["user_status"]) != "enabled",
                str(row["identity_status"]) != "enabled",
                str(row["provider_status"]) != "ACTIVE",
                str(row["credential_status"]) != "ACTIVE",
                str(row["identity_user_id"]) != context.job.app_user_id,
                str(row["identity_id"]) != snapshot.external_identity_id,
                str(row["external_subject_id"]) != snapshot.external_subject,
                str(row["provider_instance_id"]) != snapshot.provider_instance_id,
                str(metadata.get("default_team_id") or "") != snapshot.default_team_id,
                int(row.get("binding_revision") or 0) != snapshot.binding_revision,
            )
        ):
            raise ToolError("ONES subject changed; create a new Job after re-verification")
        team_ids = {str(value) for value in metadata.get("team_uuids") or []}
        if snapshot.default_team_id not in team_ids:
            raise ToolError("ONES default Team is no longer verified")
        allowed_hosts = tuple(
            str(value).lower() for value in _list(row.get("allowed_hosts_json")) if str(value)
        )
        base_url = self._validated_base_url(str(row.get("base_url") or ""), allowed_hosts)
        token = self.decryptor.decrypt(
            ciphertext=str(row["token_ciphertext"]),
            key_id=str(row["encryption_key_id"]),
        )
        return OnesCallCredential(
            credential_id=str(row["credential_id"]),
            credential_revision=int(row["credential_revision"]),
            token=token,
            base_url=base_url,
            allowed_hosts=allowed_hosts,
            external_user_id=snapshot.external_subject,
            default_team_id=snapshot.default_team_id,
        )

    def _validated_base_url(self, value: str, allowed_hosts: tuple[str, ...]) -> str:
        parsed = urlparse(value)
        hostname = (parsed.hostname or "").lower()
        if (
            parsed.scheme not in {"http", "https"}
            or not hostname
            or hostname not in allowed_hosts
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ToolError("ONES Provider configuration is invalid")
        if parsed.scheme != "https" and (
            self.environment in {"prod", "production"} or not self.allow_insecure_local
        ):
            raise ToolError("ONES Provider requires HTTPS")
        return urlunparse((parsed.scheme, parsed.netloc, "", "", "", "")).rstrip("/")


PostJson = Callable[[str, dict[str, str], dict[str, Any], float, int], Awaitable[tuple[int, bytes]]]


class HttpOnesWorkItemSearchService:
    def __init__(
        self,
        resolver: OnesRuntimeResolver,
        recorder: McpProvenanceRecorder,
        *,
        timeout_seconds: float = 8,
        max_response_bytes: int = 256 * 1024,
        post_json: PostJson | None = None,
    ) -> None:
        self.resolver = resolver
        self.recorder = recorder
        self.timeout_seconds = min(max(float(timeout_seconds), 1), 30)
        self.max_response_bytes = min(max(int(max_response_bytes), 1024), 1024 * 1024)
        self._post_json = post_json or self._http_post_json

    def prepare(self, context: AuthorizedToolContext) -> ResolvedOnesCall:
        """MCP v2 Resolve calls this so provider identity is never a Tool argument."""
        return ResolvedOnesCall(
            authorized=context,
            credential=self.resolver.resolve(context),
        )

    async def search(
        self,
        *,
        context: AuthorizedToolContext | ResolvedOnesCall,
        keyword: str,
        issue_type: Literal["demand", "task", "defect"],
        limit: int,
    ) -> OnesWorkItemSearchResult:
        started = time.monotonic()
        authorized = context.authorized if isinstance(context, ResolvedOnesCall) else context
        credential_revision = 0
        request_summary = {
            "keyword_hash": hashlib.sha256(keyword.encode()).hexdigest(),
            "keyword_length": len(keyword),
            "issue_type": issue_type,
            "limit": limit,
        }
        try:
            credential = (
                context.credential
                if isinstance(context, ResolvedOnesCall)
                else self.resolver.resolve(context)
            )
            credential_revision = credential.credential_revision
            status, raw = await self._post_json(
                credential.base_url + _SEARCH_PATH,
                {
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Ones-Auth-Token": credential.token,
                },
                {
                    "query": _SEARCH_DOCUMENT,
                    "variables": {
                        "keyword": keyword,
                        "issue_type": issue_type,
                        "limit": limit,
                        "user_id": credential.external_user_id,
                        "team_id": credential.default_team_id,
                    },
                },
                self.timeout_seconds,
                self.max_response_bytes,
            )
            if status == 401:
                self.resolver.store.query.execute(
                    """
                    update provider_credential
                       set status = 'INVALID', last_error_code = 'ones_unauthorized',
                           last_error_at = current_timestamp, updated_at = current_timestamp
                     where id = ? and status = 'ACTIVE'
                    """,
                    (credential.credential_id,),
                )
                raise ToolError("ONES credential is invalid; re-verification is required")
            if status == 403:
                raise ToolError("ONES denied access for the verified user")
            if status == 429 or status >= 500:
                raise ToolError("ONES is temporarily unavailable")
            if status != 200:
                raise ToolError("ONES request was rejected")
            if len(raw) > self.max_response_bytes:
                raise ToolError("ONES result exceeds the response size limit")
            result = OnesWorkItemSearchResult.model_validate(
                sanitize_sensitive_data(_parse_result(raw, limit=limit).model_dump())
            )
            self.recorder.record(
                context=authorized,
                request_summary=request_summary,
                result_payload=result.model_dump(),
                status="SUCCEEDED",
                duration_ms=int((time.monotonic() - started) * 1000),
                credential_revision=credential_revision,
            )
            return result
        except Exception as exc:
            self.recorder.record(
                context=authorized,
                request_summary=request_summary,
                result_payload={"error_code": _error_code(exc)},
                status="FAILED",
                duration_ms=int((time.monotonic() - started) * 1000),
                credential_revision=credential_revision,
                error_code=_error_code(exc),
            )
            raise

    @staticmethod
    async def _http_post_json(
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> tuple[int, bytes]:
        def call() -> tuple[int, bytes]:
            request = Request(
                url,
                data=json.dumps(payload, ensure_ascii=False).encode(),
                headers=headers,
                method="POST",
            )
            opener = build_opener(ProxyHandler({}), _NoRedirectHandler())
            try:
                with opener.open(request, timeout=timeout_seconds) as response:
                    raw = response.read(max_response_bytes + 1)
                    return int(getattr(response, "status", 200)), raw
            except HTTPError as exc:
                return int(exc.code), exc.read(max_response_bytes + 1)
            except (URLError, TimeoutError, OSError) as exc:
                raise ToolError("ONES is temporarily unavailable") from exc

        return await asyncio.to_thread(call)


def build_default_ones_service(store: PlatformRuntimeStore) -> HttpOnesWorkItemSearchService:
    decryptor = ProviderTokenDecryptor.from_file(os.environ.get("APP_CONFIG_MASTER_KEY_FILE", ""))
    resolver = OnesRuntimeResolver(
        store,
        decryptor,
        environment=os.environ.get("APP_ENV", "local"),
        allow_insecure_local=os.environ.get("ONES_ALLOW_INSECURE_LOCAL", "").lower()
        in {"1", "true", "yes", "on"},
    )
    return HttpOnesWorkItemSearchService(
        resolver,
        McpProvenanceRecorder(
            store.query,
            server_code=SERVER_CODE,
            server_version=SERVER_VERSION,
        ),
        timeout_seconds=float(os.environ.get("ONES_MCP_PROVIDER_TIMEOUT_SECONDS", "8")),
        max_response_bytes=int(
            os.environ.get("ONES_MCP_MAX_PROVIDER_RESPONSE_BYTES", str(256 * 1024))
        ),
    )


def _parse_result(raw: bytes, *, limit: int) -> OnesWorkItemSearchResult:
    try:
        payload = json.loads(raw.decode())
        result = payload["data"]["workItems"]
        raw_items = result["items"]
        total = int(result["total"])
        truncated = bool(result["truncated"])
        if not isinstance(raw_items, list):
            raise TypeError
        items = tuple(OnesWorkItem.model_validate(item) for item in raw_items[:limit])
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ToolError("ONES returned an invalid bounded response") from exc
    return OnesWorkItemSearchResult(
        items=items,
        total=max(0, total),
        truncated=truncated or len(raw_items) > limit,
    )


def _object(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _list(value: Any) -> list[Any]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _error_code(exc: Exception) -> str:
    text = str(exc).lower()
    if "credential is invalid" in text:
        return "ones_unauthorized"
    if "denied access" in text:
        return "ones_forbidden"
    if "size limit" in text:
        return "ones_result_too_large"
    if "subject" in text or "verification" in text:
        return "ones_subject_unavailable"
    return "ones_provider_error"


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
