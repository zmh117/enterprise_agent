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
MAX_GRAPHQL_LIST_RESULTS = 500
MAX_PROVIDER_CURSOR_CHARS = 512
_CURSOR_PURPOSE = "ones-work-item-search"
_GRAPHQL_LIST_CURSOR_PURPOSE = "ones-graphql-list"


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


@dataclass(frozen=True, slots=True)
class OnesGraphqlListPage:
    mode: str
    provider_cursor: str = ""
    offset: int = 0
    collection_fingerprint: str = ""
    cumulative_returned: int = 0

    @property
    def remaining(self) -> int:
        return MAX_GRAPHQL_LIST_RESULTS - self.cumulative_returned


class OnesGraphqlListCursorCodec:
    PROVIDER_MODE = "provider"
    SNAPSHOT_OFFSET_MODE = "snapshot_offset"
    MODES = frozenset({PROVIDER_MODE, SNAPSHOT_OFFSET_MODE})

    @classmethod
    def first_page(cls, mode: str) -> OnesGraphqlListPage:
        cls._require_mode(mode)
        return OnesGraphqlListPage(mode=mode)

    @classmethod
    def decode(
        cls,
        cursor: str,
        *,
        tool_identifier: str,
        input_schema: dict[str, Any],
        mode: str,
        claims: dict[str, Any],
        principal: ResolvedOnesPrincipal,
        request: dict[str, Any],
    ) -> OnesGraphqlListPage:
        cls._require_mode(mode)
        if not cursor:
            return cls.first_page(mode)
        position = ToolPaginationCursorCodec.decode(
            cursor,
            context=cls._context(claims, principal, input_schema),
            purpose=f"{_GRAPHQL_LIST_CURSOR_PURPOSE}:{tool_identifier}",
            request=cls._request_binding(request),
            state_fingerprint=cls._state_fingerprint(principal),
        )
        if not isinstance(position, dict) or set(position) != {
            "mode",
            "provider_cursor",
            "offset",
            "collection_fingerprint",
            "cumulative_returned",
        }:
            raise cls._invalid()
        mode_value = position.get("mode")
        provider_cursor = position.get("provider_cursor")
        offset = position.get("offset")
        collection_fingerprint = position.get("collection_fingerprint")
        cumulative_returned = position.get("cumulative_returned")
        if (
            not isinstance(mode_value, str)
            or not isinstance(provider_cursor, str)
            or type(offset) is not int
            or not isinstance(collection_fingerprint, str)
            or type(cumulative_returned) is not int
        ):
            raise cls._invalid()
        page = OnesGraphqlListPage(
            mode=mode_value,
            provider_cursor=provider_cursor,
            offset=offset,
            collection_fingerprint=collection_fingerprint,
            cumulative_returned=cumulative_returned,
        )
        cls._validate_page(page, expected_mode=mode)
        return page

    @classmethod
    def encode(
        cls,
        *,
        page: OnesGraphqlListPage,
        tool_identifier: str,
        input_schema: dict[str, Any],
        claims: dict[str, Any],
        principal: ResolvedOnesPrincipal,
        request: dict[str, Any],
    ) -> str:
        cls._validate_page(page, expected_mode=page.mode)
        return ToolPaginationCursorCodec.encode(
            context=cls._context(claims, principal, input_schema),
            purpose=f"{_GRAPHQL_LIST_CURSOR_PURPOSE}:{tool_identifier}",
            request=cls._request_binding(request),
            state_fingerprint=cls._state_fingerprint(principal),
            position={
                "mode": page.mode,
                "provider_cursor": page.provider_cursor,
                "offset": page.offset,
                "collection_fingerprint": page.collection_fingerprint,
                "cumulative_returned": page.cumulative_returned,
            },
        )

    @classmethod
    def _validate_page(
        cls,
        page: OnesGraphqlListPage,
        *,
        expected_mode: str,
    ) -> None:
        cls._require_mode(expected_mode)
        if (
            page.mode != expected_mode
            or not isinstance(page.provider_cursor, str)
            or type(page.offset) is not int
            or not isinstance(page.collection_fingerprint, str)
            or type(page.cumulative_returned) is not int
            or not 1 <= page.cumulative_returned < MAX_GRAPHQL_LIST_RESULTS
        ):
            raise cls._invalid()
        if page.mode == cls.PROVIDER_MODE:
            if (
                not page.provider_cursor
                or len(page.provider_cursor) > MAX_PROVIDER_CURSOR_CHARS
                or page.offset != 0
                or page.collection_fingerprint
            ):
                raise cls._invalid()
            return
        if (
            page.provider_cursor
            or page.offset <= 0
            or page.offset != page.cumulative_returned
            or len(page.collection_fingerprint) != 64
            or any(
                character not in "0123456789abcdef"
                for character in page.collection_fingerprint.lower()
            )
        ):
            raise cls._invalid()

    @staticmethod
    def _request_binding(request: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in request.items() if key != "cursor"}

    @staticmethod
    def _context(
        claims: dict[str, Any],
        principal: ResolvedOnesPrincipal,
        input_schema: dict[str, Any],
    ) -> ToolRequestContext:
        snapshot_hash = ToolPaginationCursorCodec.fingerprint(
            {
                "agent_publication_id": principal.agent_publication_id,
                "application_publication_id": principal.application_publication_id,
                "tool_schema_hash": tool_schema_hash(input_schema),
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

    @classmethod
    def _require_mode(cls, mode: str) -> None:
        if not isinstance(mode, str) or mode not in cls.MODES:
            raise cls._invalid()

    @staticmethod
    def _invalid() -> ToolPolicyError:
        return ToolPolicyError(
            "ONES GraphQL list pagination cursor is invalid",
            safe_message="分页游标无效，请从第一页重新查询",
            error_code="mcp_pagination_cursor_invalid",
        )

    @staticmethod
    def stale() -> ToolPolicyError:
        return ToolPolicyError(
            "ONES GraphQL snapshot changed during pagination",
            safe_message="分页期间 ONES 列表已变化，请从第一页重新查询",
            error_code="mcp_pagination_cursor_stale",
        )
