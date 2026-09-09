"""Bounded, invocation-local collection; provider cursors never reach the model."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from services.ones_mcp_server.errors import OnesMcpError, invalid_provider_response

PAGE_SIZE = 200
MAX_RESULTS = 1000
MAX_PAGES = 50
MAX_SECONDS = 90
MAX_RESULT_BYTES = 8 * 1024 * 1024


def collect_pages(
    fetch: Callable[[dict[str, Any]], dict[str, Any]],
    arguments: dict[str, Any],
    *,
    field: str,
    direct_list: bool = False,
) -> dict[str, Any]:
    """Publish only a validated collection, never a successful partial failure."""
    limit = arguments["limit"]
    if type(limit) is not int or not 1 <= limit <= MAX_RESULTS:
        raise invalid_provider_response("ones_provider_schema_invalid")
    started = time.monotonic()
    items: list[dict[str, Any]] = []
    identities: set[object] = set()
    cursors: set[str] = set()
    cursor = ""
    size = 0
    for page_number in range(1, MAX_PAGES + 1):
        if time.monotonic() - started >= MAX_SECONDS:
            raise OnesMcpError(
                "ONES collection deadline exceeded",
                safe_message="ONES 自动翻页超时，结果未标记为完整，请缩小查询范围后重试",
                error_code="ones_collection_timeout",
            )
        page_limit = limit if direct_list else min(PAGE_SIZE, limit - len(items))
        output = fetch(
            {
                **arguments,
                "limit": page_limit,
                "provider_cursor": cursor,
                "cumulative_returned": len(items),
                "page_offset": 0,
            }
        )
        page = output.get(field)
        total = output.get("total")
        more = output.get("truncated")
        if (
            not isinstance(page, list)
            or len(page) > page_limit
            or type(total) is not int
            or total < 0
            or type(more) is not bool
        ):
            raise invalid_provider_response("ones_provider_schema_invalid")
        for item in page:
            if not isinstance(item, dict):
                raise invalid_provider_response("ones_provider_schema_invalid")
            identity = item.get("uuid", item.get("number"))
            if not isinstance(identity, (str, int)) or isinstance(identity, bool):
                raise invalid_provider_response("ones_provider_schema_invalid")
            if identity in identities:
                raise invalid_provider_response("ones_pagination_unstable")
            identities.add(identity)
        size += len(json.dumps(page, ensure_ascii=False).encode("utf-8"))
        if size > MAX_RESULT_BYTES:
            raise invalid_provider_response("ones_collection_size_exceeded")
        items.extend(page)
        if not more or len(items) == limit or direct_list:
            return {
                field: items,
                "total": total,
                "returned": len(items),
                "cumulative_returned": len(items),
                "truncated": more,
                "pagination_limit_reached": more and len(items) == limit,
                "untrusted_data": True,
            }
        next_cursor = output.get("_provider_cursor")
        if not page or not isinstance(next_cursor, str) or not next_cursor:
            raise invalid_provider_response("ones_pagination_cursor_missing")
        if next_cursor in cursors:
            raise invalid_provider_response("ones_pagination_unstable")
        cursors.add(next_cursor)
        cursor = next_cursor
    raise invalid_provider_response("ones_collection_page_limit")
