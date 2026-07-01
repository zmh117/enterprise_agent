from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
from collections.abc import Callable
from typing import Any, Protocol
from urllib.request import Request, urlopen

from app.modules.local_internal_api_platform.envelope import safe_error_text
from app.modules.local_internal_api_platform.loki_gateway import (
    build_logql,
    summarize_loki_response,
)
from app.modules.local_internal_api_platform.schemas import LokiQuery

from ..domain.addressing import ResourceBinding
from ..domain.errors import PolicyViolation, ResolutionError, UpstreamUnavailable
from ..domain.results import ToolResponse

_RETRYABLE_UPSTREAM_STATUSES = {429, 502, 503, 504}


class LokiClient(Protocol):
    def query(
        self,
        binding: ResourceBinding,
        *,
        selector: dict[str, str],
        query: str,
        minutes: int,
        limit: int,
    ) -> ToolResponse: ...


class HttpLokiClient:
    """Base-level Loki client. Reuses LogQL build/summarize but manages its own fetch."""

    def __init__(
        self,
        *,
        max_minutes: int,
        max_lines: int,
        max_response_chars: int,
        urlopen_func: Callable[..., Any] = urlopen,
    ) -> None:
        self._max_minutes = max_minutes
        self._max_lines = max_lines
        self._max_response_chars = max_response_chars
        self._urlopen_func = urlopen_func

    def query(
        self,
        binding: ResourceBinding,
        *,
        selector: dict[str, str],
        query: str,
        minutes: int,
        limit: int,
    ) -> ToolResponse:
        if binding.loki is None:
            raise ResolutionError("Base has no loki connection configured")
        if minutes < 1 or minutes > self._max_minutes:
            raise PolicyViolation("Loki time range exceeds configured maximum")
        if limit < 1 or limit > self._max_lines:
            raise PolicyViolation("Loki result size exceeds configured maximum")

        logql = build_logql(selector, query)
        loki_query = LokiQuery(
            selector=selector, query=query, minutes=minutes, limit=limit, logql=logql
        )
        body = self._fetch(binding, loki_query)
        result = summarize_loki_response(body, loki_query, self._max_response_chars)
        return ToolResponse(
            summary=result.summary,
            raw=result.raw,
            truncated=result.truncated,
            metadata=result.metadata,
        )

    def _fetch(self, binding: ResourceBinding, loki_query: LokiQuery) -> dict[str, Any]:
        assert binding.loki is not None
        end_ns = time.time_ns()
        start_ns = end_ns - loki_query.minutes * 60 * 1_000_000_000
        params = urllib.parse.urlencode(
            {
                "query": loki_query.logql,
                "start": str(start_ns),
                "end": str(end_ns),
                "limit": str(loki_query.limit),
                "direction": "backward",
            }
        )
        url = f"{binding.loki.base_url.rstrip('/')}/loki/api/v1/query_range?{params}"
        headers = {"accept": "application/json"}
        if binding.loki.tenant:
            headers["X-Scope-OrgID"] = binding.loki.tenant
        request = Request(url, headers=headers, method="GET")
        try:
            with self._urlopen_func(request, timeout=10) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in _RETRYABLE_UPSTREAM_STATUSES:
                raise UpstreamUnavailable(f"Loki transient error ({exc.code})") from exc
            raise PolicyViolation(f"Loki rejected query ({exc.code})") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise UpstreamUnavailable(f"Loki request failed: {safe_error_text(str(exc))}") from exc
        except json.JSONDecodeError as exc:
            raise UpstreamUnavailable("Loki returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise UpstreamUnavailable("Loki returned invalid JSON")
        return parsed


class FakeLokiClient:
    def __init__(self, highlights: list[str] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._highlights = highlights or ["MaterialNotEnoughException"]

    def query(
        self,
        binding: ResourceBinding,
        *,
        selector: dict[str, str],
        query: str,
        minutes: int,
        limit: int,
    ) -> ToolResponse:
        self.calls.append({"selector": selector, "query": query, "minutes": minutes})
        return ToolResponse(
            summary={
                "selector": selector,
                "line_count": len(self._highlights),
                "highlights": self._highlights,
            }
        )
