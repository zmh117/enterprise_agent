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
from ..domain.loki_policy import ALLOWED_SELECTOR_LABELS
from ..domain.results import ToolResponse

_RETRYABLE_UPSTREAM_STATUSES = {429, 502, 503, 504}


class LokiClient(Protocol):
    def labels(
        self,
        binding: ResourceBinding,
        *,
        selector: dict[str, str],
        minutes: int,
        limit: int,
    ) -> ToolResponse: ...

    def label_values(
        self,
        binding: ResourceBinding,
        *,
        label: str,
        selector: dict[str, str],
        minutes: int,
        limit: int,
    ) -> ToolResponse: ...

    def probe(
        self,
        binding: ResourceBinding,
        *,
        selector: dict[str, str],
        query: str,
        minutes: int,
        limit: int,
    ) -> ToolResponse: ...

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

    def labels(
        self,
        binding: ResourceBinding,
        *,
        selector: dict[str, str],
        minutes: int,
        limit: int,
    ) -> ToolResponse:
        self._validate_binding_and_bounds(binding, minutes=minutes, limit=limit)
        if selector:
            body = self._fetch_series(binding, selector=selector, minutes=minutes)
            values = sorted(
                {
                    label
                    for series in _series_items(body)
                    for label in series
                    if label in ALLOWED_SELECTOR_LABELS
                }
            )
        else:
            body = self._fetch_json(
                binding,
                "/loki/api/v1/labels",
                self._range_params(minutes),
            )
            raw_values = _nested_value(body, ["data"])
            values = (
                sorted(str(value) for value in raw_values if str(value) in ALLOWED_SELECTOR_LABELS)
                if isinstance(raw_values, list)
                else []
            )
        bounded, truncated = _bounded_strings(values, limit=limit)
        return ToolResponse(
            summary={
                "selector": selector,
                "minutes": minutes,
                "labels": bounded,
                "label_count": len(bounded),
                "tenant_configured": bool(binding.loki and binding.loki.tenant),
                "truncated": truncated,
            },
            raw={"label_count": len(values)},
            truncated=truncated,
            metadata={"source": "internal-api-platform-loki-diagnostics"},
        )

    def label_values(
        self,
        binding: ResourceBinding,
        *,
        label: str,
        selector: dict[str, str],
        minutes: int,
        limit: int,
    ) -> ToolResponse:
        self._validate_binding_and_bounds(binding, minutes=minutes, limit=limit)
        if selector:
            body = self._fetch_series(binding, selector=selector, minutes=minutes)
            values = sorted(
                {
                    str(series[label])
                    for series in _series_items(body)
                    if label in series and series[label] is not None
                }
            )
        else:
            encoded = urllib.parse.quote(label, safe="")
            body = self._fetch_json(
                binding,
                f"/loki/api/v1/label/{encoded}/values",
                self._range_params(minutes),
            )
            raw_values = _nested_value(body, ["data"])
            values = (
                sorted(str(value) for value in raw_values) if isinstance(raw_values, list) else []
            )
        bounded, truncated = _bounded_strings(values, limit=limit)
        return ToolResponse(
            summary={
                "selector": selector,
                "label": label,
                "minutes": minutes,
                "values": bounded,
                "value_count": len(bounded),
                "tenant_configured": bool(binding.loki and binding.loki.tenant),
                "truncated": truncated,
            },
            raw={"value_count": len(values)},
            truncated=truncated,
            metadata={"source": "internal-api-platform-loki-diagnostics"},
        )

    def probe(
        self,
        binding: ResourceBinding,
        *,
        selector: dict[str, str],
        query: str,
        minutes: int,
        limit: int,
    ) -> ToolResponse:
        result = self.query(
            binding,
            selector=selector,
            query=query,
            minutes=minutes,
            limit=limit,
        )
        result.metadata.setdefault("source", "internal-api-platform-loki-diagnostics")
        result.summary.setdefault("diagnostic_action", "inspect_selector_time_range_and_keyword")
        return result

    def _fetch(self, binding: ResourceBinding, loki_query: LokiQuery) -> dict[str, Any]:
        params = self._range_params(loki_query.minutes)
        params.update(
            {
                "query": loki_query.logql,
                "limit": str(loki_query.limit),
                "direction": "backward",
            }
        )
        return self._fetch_json(binding, "/loki/api/v1/query_range", params)

    def _fetch_series(
        self,
        binding: ResourceBinding,
        *,
        selector: dict[str, str],
        minutes: int,
    ) -> dict[str, Any]:
        params: list[tuple[str, str]] = list(self._range_params(minutes).items())
        params.append(("match[]", build_logql(selector, "")))
        return self._fetch_json(binding, "/loki/api/v1/series", params)

    def _fetch_json(
        self,
        binding: ResourceBinding,
        path: str,
        params: dict[str, str] | list[tuple[str, str]],
    ) -> dict[str, Any]:
        assert binding.loki is not None
        query_string = urllib.parse.urlencode(params)
        url = f"{binding.loki.base_url.rstrip('/')}{path}?{query_string}"
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
        if parsed.get("status") not in {None, "success"}:
            message = safe_error_text(str(parsed.get("error") or "Loki request failed"))
            raise UpstreamUnavailable(f"Loki returned error: {message}")
        return parsed

    def _validate_binding_and_bounds(
        self,
        binding: ResourceBinding,
        *,
        minutes: int,
        limit: int,
    ) -> None:
        if binding.loki is None:
            raise ResolutionError("Base has no loki connection configured")
        if minutes < 1 or minutes > self._max_minutes:
            raise PolicyViolation("Loki time range exceeds configured maximum")
        if limit < 1 or limit > self._max_lines:
            raise PolicyViolation("Loki result size exceeds configured maximum")

    @staticmethod
    def _range_params(minutes: int) -> dict[str, str]:
        end_ns = time.time_ns()
        start_ns = end_ns - minutes * 60 * 1_000_000_000
        return {"start": str(start_ns), "end": str(end_ns)}


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
                "stream_count": 1,
                "line_count": len(self._highlights),
                "highlights": self._highlights,
                "empty_result_hints": [] if self._highlights else ["No matching logs in fake Loki"],
            }
        )

    def labels(
        self,
        binding: ResourceBinding,
        *,
        selector: dict[str, str],
        minutes: int,
        limit: int,
    ) -> ToolResponse:
        self.calls.append({"diagnostic": "labels", "selector": selector, "minutes": minutes})
        labels = sorted({"service", "workshop", *selector.keys()})[:limit]
        return ToolResponse(
            summary={
                "selector": selector,
                "minutes": minutes,
                "labels": labels,
                "label_count": len(labels),
                "tenant_configured": bool(binding.loki and binding.loki.tenant),
                "truncated": False,
            },
            raw={"label_count": len(labels)},
            metadata={"source": "internal-api-platform-loki-diagnostics"},
        )

    def label_values(
        self,
        binding: ResourceBinding,
        *,
        label: str,
        selector: dict[str, str],
        minutes: int,
        limit: int,
    ) -> ToolResponse:
        self.calls.append(
            {"diagnostic": "label_values", "label": label, "selector": selector, "minutes": minutes}
        )
        values = [selector[label]] if label in selector else [f"{label}-value"]
        return ToolResponse(
            summary={
                "selector": selector,
                "label": label,
                "minutes": minutes,
                "values": values[:limit],
                "value_count": len(values[:limit]),
                "tenant_configured": bool(binding.loki and binding.loki.tenant),
                "truncated": len(values) > limit,
            },
            raw={"value_count": len(values)},
            truncated=len(values) > limit,
            metadata={"source": "internal-api-platform-loki-diagnostics"},
        )

    def probe(
        self,
        binding: ResourceBinding,
        *,
        selector: dict[str, str],
        query: str,
        minutes: int,
        limit: int,
    ) -> ToolResponse:
        self.calls.append({"diagnostic": "probe", "selector": selector, "query": query})
        return self.query(
            binding,
            selector=selector,
            query=query,
            minutes=minutes,
            limit=limit,
        )


def _series_items(body: dict[str, Any]) -> list[dict[str, str]]:
    result = _nested_value(body, ["data"])
    if not isinstance(result, list):
        return []
    return [item for item in result if isinstance(item, dict)]


def _nested_value(value: dict[str, Any], keys: list[str]) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _bounded_strings(values: list[str], *, limit: int) -> tuple[list[str], bool]:
    redacted = [safe_error_text(value, max_chars=200) for value in values]
    return redacted[:limit], len(redacted) > limit
