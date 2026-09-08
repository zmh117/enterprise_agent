from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.mcp_tool_runtime.contracts import ToolRequestContext
from app.modules.mcp_tool_runtime.pagination import ToolPaginationCursorCodec
from app.shared.exceptions import ToolPolicyError
from app.shared.tool_contract import tool_schema_hash
from services.ones_mcp_server.auth.principal import ResolvedOnesPrincipal
from services.ones_mcp_server.contracts import TOOL_INPUT_SCHEMA


MAX_WORK_ITEM_SEARCH_RESULTS = 500
MAX_PROVIDER_CURSOR_CHARS = 512
_CURSOR_PURPOSE = "ones-work-item-search"


@dataclass(frozen=True, slots=True)
class OnesWorkItemSearchPage:
    provider_cursor: str = ""
    cumulative_returned: int = 0

    @property
    def remaining(self) -> int:
        return MAX_WORK_ITEM_SEARCH_RESULTS - self.cumulative_returned


class OnesWorkItemSearchCursorCodec:
    @classmethod
    def decode(
        cls,
        cursor: str,
        *,
        claims: dict[str, Any],
        principal: ResolvedOnesPrincipal,
        request: dict[str, Any],
    ) -> OnesWorkItemSearchPage:
        if not cursor:
            return OnesWorkItemSearchPage()
        position = ToolPaginationCursorCodec.decode(
            cursor,
            context=cls._context(claims, principal),
            purpose=_CURSOR_PURPOSE,
            request=cls._request_binding(request),
            state_fingerprint=cls._state_fingerprint(principal),
        )
        if not isinstance(position, dict) or set(position) != {
            "provider_cursor",
            "cumulative_returned",
        }:
            raise cls._invalid()
        provider_cursor = position.get("provider_cursor")
        cumulative_returned = position.get("cumulative_returned")
        if (
            not isinstance(provider_cursor, str)
            or not provider_cursor
            or len(provider_cursor) > MAX_PROVIDER_CURSOR_CHARS
            or type(cumulative_returned) is not int
            or not 1 <= cumulative_returned < MAX_WORK_ITEM_SEARCH_RESULTS
        ):
            raise cls._invalid()
        return OnesWorkItemSearchPage(
            provider_cursor=provider_cursor,
            cumulative_returned=cumulative_returned,
        )

    @classmethod
    def encode(
        cls,
        *,
        provider_cursor: str,
        cumulative_returned: int,
        claims: dict[str, Any],
        principal: ResolvedOnesPrincipal,
        request: dict[str, Any],
    ) -> str:
        if (
            not provider_cursor
            or len(provider_cursor) > MAX_PROVIDER_CURSOR_CHARS
            or not 1 <= cumulative_returned < MAX_WORK_ITEM_SEARCH_RESULTS
        ):
            raise cls._invalid()
        return ToolPaginationCursorCodec.encode(
            context=cls._context(claims, principal),
            purpose=_CURSOR_PURPOSE,
            request=cls._request_binding(request),
            state_fingerprint=cls._state_fingerprint(principal),
            position={
                "provider_cursor": provider_cursor,
                "cumulative_returned": cumulative_returned,
            },
        )

    @staticmethod
    def _request_binding(request: dict[str, Any]) -> dict[str, Any]:
        return {
            "keyword": request["keyword"],
            "issue_type": request["issue_type"],
            "limit": request["limit"],
        }

    @staticmethod
    def _context(
        claims: dict[str, Any],
        principal: ResolvedOnesPrincipal,
    ) -> ToolRequestContext:
        snapshot_hash = ToolPaginationCursorCodec.fingerprint(
            {
                "agent_publication_id": principal.agent_publication_id,
                "application_publication_id": principal.application_publication_id,
                "tool_schema_hash": tool_schema_hash(TOOL_INPUT_SCHEMA),
            }
        )
        return ToolRequestContext(
            job_id=principal.job_id,
            user_id=principal.actor_user_id,
            project_code="",
            application_id=principal.business_application_id,
            snapshot_hash=snapshot_hash,
            authorization_hash=str(claims.get("authorization_hash") or ""),
        )

    @staticmethod
    def _state_fingerprint(principal: ResolvedOnesPrincipal) -> str:
        return ToolPaginationCursorCodec.fingerprint(
            {
                "external_identity_id": principal.external_identity_id,
                "provider_user_id": principal.provider_user_id,
                "team_id": principal.team_id,
            }
        )

    @staticmethod
    def _invalid() -> ToolPolicyError:
        return ToolPolicyError(
            "ONES work item pagination cursor is invalid",
            safe_message="分页游标无效，请从第一页重新查询",
            error_code="mcp_pagination_cursor_invalid",
        )
