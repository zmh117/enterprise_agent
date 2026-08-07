from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import json
import re
import socket
from typing import Any, Protocol
import urllib.error
import urllib.parse
from urllib.request import Request, urlopen

from app.modules.permission.application.permission_service import PermissionService
from app.modules.platform_config.domain.provider_contracts import ProviderContractRegistry
from app.modules.platform_config.infrastructure.governed_resource_repository import (
    GovernedResourceRepository,
)
from app.modules.platform_config.infrastructure.repository import new_id
from app.shared.database import assert_external_io_allowed
from app.shared.exceptions import NonRetryableExecutionError


_LABEL_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")
_FORBIDDEN_EXACT_VALUE_FRAGMENTS = ("*", "?", "!=", "=~", "!~", "|", "{", "}")
_MAX_CONDITIONS = 8
_MAX_LABEL_KEYS = 64
_MAX_LABEL_VALUES = 100
_MAX_DISCOVERY_BYTES = 32 * 1024
_MAX_DISCOVERY_MINUTES = 60


class LokiDraftDiscoveryGateway(Protocol):
    def test_and_labels(
        self,
        *,
        draft: dict[str, Any],
        minutes: int,
    ) -> list[str]: ...

    def label_values(
        self,
        *,
        draft: dict[str, Any],
        label: str,
        conditions: dict[str, str],
        minutes: int,
    ) -> list[str]: ...


class HttpLokiDraftDiscoveryGateway:
    def __init__(
        self,
        *,
        resolve_secret: Callable[[str], str],
        urlopen_func: Callable[..., Any] = urlopen,
        provider_contracts: ProviderContractRegistry | None = None,
    ) -> None:
        self._resolve_secret = resolve_secret
        self._urlopen = urlopen_func
        self._provider_contracts = provider_contracts or ProviderContractRegistry()

    def test_and_labels(
        self,
        *,
        draft: dict[str, Any],
        minutes: int,
    ) -> list[str]:
        runtime = self._runtime(draft)
        try:
            self._fetch(runtime, "/loki/api/v1/status/buildinfo", {})
            body = self._fetch(runtime, "/loki/api/v1/labels", self._range(minutes))
            data = body.get("data")
            return [str(item) for item in data] if isinstance(data, list) else []
        finally:
            runtime.pop("auth_token", None)

    def label_values(
        self,
        *,
        draft: dict[str, Any],
        label: str,
        conditions: dict[str, str],
        minutes: int,
    ) -> list[str]:
        runtime = self._runtime(draft)
        try:
            if conditions:
                params: list[tuple[str, str]] = list(self._range(minutes).items())
                params.append(("match[]", _exact_selector(conditions)))
                body = self._fetch(runtime, "/loki/api/v1/series", params)
                series = body.get("data")
                return [
                    str(item[label])
                    for item in (series if isinstance(series, list) else [])
                    if isinstance(item, dict) and item.get(label) is not None
                ]
            encoded = urllib.parse.quote(label, safe="")
            body = self._fetch(
                runtime,
                f"/loki/api/v1/label/{encoded}/values",
                self._range(minutes),
            )
            data = body.get("data")
            return [str(item) for item in data] if isinstance(data, list) else []
        finally:
            runtime.pop("auth_token", None)

    def _runtime(self, draft: dict[str, Any]) -> dict[str, Any]:
        document = self._provider_contracts.normalize(
            provider_type=str(draft["provider_type"]),
            config=dict(draft["config"]),
            secret_refs=dict(draft["secret_refs"]),
        )
        return self._provider_contracts.runtime_projection(
            document,
            resolve_secret=self._resolve_secret,
        )

    def _fetch(
        self,
        runtime: dict[str, Any],
        path: str,
        params: dict[str, str] | list[tuple[str, str]],
    ) -> dict[str, Any]:
        assert_external_io_allowed("loki_draft_discovery.http")
        url = f"{str(runtime['base_url']).rstrip('/')}{path}"
        query = urllib.parse.urlencode(params)
        if query:
            url = f"{url}?{query}"
        headers = {"accept": "application/json"}
        if runtime.get("tenant"):
            headers["X-Scope-OrgID"] = str(runtime["tenant"])
        if runtime.get("auth_token"):
            headers["Authorization"] = f"Bearer {runtime['auth_token']}"
        request = Request(url, headers=headers, method="GET")
        try:
            with self._urlopen(
                request,
                timeout=min(int(runtime["timeout_seconds"]), 10),
            ) as response:
                raw = response.read(int(runtime["max_response_bytes"]) + 1)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, socket.timeout):
            raise _discovery_error("Loki 连接或标签发现失败") from None
        if len(raw) > int(runtime["max_response_bytes"]):
            raise _discovery_error("Loki 标签发现响应超过字节上限")
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise _discovery_error("Loki 标签发现返回无效响应") from None
        if not isinstance(parsed, dict) or parsed.get("status") not in {None, "success"}:
            raise _discovery_error("Loki 拒绝了标签发现请求")
        return parsed

    @staticmethod
    def _range(minutes: int) -> dict[str, str]:
        end_ns = int(datetime.now(UTC).timestamp() * 1_000_000_000)
        return {
            "start": str(end_ns - minutes * 60 * 1_000_000_000),
            "end": str(end_ns),
        }


class LokiDraftDiscoveryService:
    def __init__(
        self,
        repository: GovernedResourceRepository,
        permission_service: PermissionService,
        gateway: LokiDraftDiscoveryGateway,
        *,
        session_ttl_seconds: int = 300,
    ) -> None:
        self.repository = repository
        self.permission_service = permission_service
        self.gateway = gateway
        self.session_ttl_seconds = max(60, min(int(session_ttl_seconds), 900))

    def test_draft(
        self,
        code: str,
        *,
        actor_id: str,
        minutes: int = 15,
        limit: int = _MAX_LABEL_KEYS,
    ) -> dict[str, Any]:
        self._require_admin(actor_id)
        resource, draft = self._loki_draft(code)
        effective_minutes = _minutes(minutes, draft)
        effective_limit = _limit(limit, _MAX_LABEL_KEYS)
        labels = self.gateway.test_and_labels(
            draft=draft,
            minutes=effective_minutes,
        )
        bounded, truncated = _bounded_strings(labels, limit=effective_limit)
        timestamp = datetime.now(UTC)
        session_id = new_id("loki_draft_test")
        with self.repository.database.unit_of_work():
            current_resource, current = self._loki_draft(code)
            if (
                current_resource["id"] != resource["id"]
                or current["id"] != draft["id"]
                or int(current["draft_revision"]) != int(draft["draft_revision"])
                or str(current["content_hash"]) != str(draft["content_hash"])
            ):
                raise _session_error("Loki Resource Draft 在测试期间已变化")
            self.repository.database.execute(
                """
                update loki_resource_draft_test_session
                   set status = 'EXPIRED'
                 where resource_id = ? and actor_id = ? and status = 'ACTIVE'
                """,
                (resource["id"], actor_id),
            )
            self.repository.database.execute(
                """
                insert into loki_resource_draft_test_session
                  (id, resource_id, draft_id, draft_revision, content_hash,
                   actor_id, status, expires_at, created_at)
                values (?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?)
                """,
                (
                    session_id,
                    resource["id"],
                    draft["id"],
                    int(draft["draft_revision"]),
                    draft["content_hash"],
                    actor_id,
                    (timestamp + timedelta(seconds=self.session_ttl_seconds)).isoformat(),
                    timestamp.isoformat(),
                ),
            )
        return {
            "test_session_id": session_id,
            "draft_revision": int(draft["draft_revision"]),
            "labels": bounded,
            "label_count": len(bounded),
            "truncated": truncated,
            "expires_at": (timestamp + timedelta(seconds=self.session_ttl_seconds)).isoformat(),
        }

    def label_values(
        self,
        code: str,
        *,
        test_session_id: str,
        label: str,
        selected_conditions: object,
        actor_id: str,
        minutes: int = 15,
        limit: int = _MAX_LABEL_VALUES,
    ) -> dict[str, Any]:
        self._require_admin(actor_id)
        resource, draft = self._loki_draft(code)
        self._require_session(
            session_id=test_session_id,
            resource=resource,
            draft=draft,
            actor_id=actor_id,
        )
        normalized_label = _label_key(label)
        conditions = normalize_exact_conditions(selected_conditions)
        if normalized_label in conditions:
            raise _discovery_error("待发现 label 不能与已选条件重复")
        effective_minutes = _minutes(minutes, draft)
        effective_limit = _limit(limit, _MAX_LABEL_VALUES)
        values = self.gateway.label_values(
            draft=draft,
            label=normalized_label,
            conditions=conditions,
            minutes=effective_minutes,
        )
        bounded, truncated = _bounded_strings(values, limit=effective_limit)
        _, current = self._loki_draft(code)
        if (
            current["id"] != draft["id"]
            or int(current["draft_revision"]) != int(draft["draft_revision"])
            or str(current["content_hash"]) != str(draft["content_hash"])
        ):
            raise _session_error("Loki Resource Draft 在发现期间已变化")
        return {
            "label": normalized_label,
            "values": bounded,
            "value_count": len(bounded),
            "truncated": truncated,
        }

    def _loki_draft(self, code: str) -> tuple[dict[str, Any], dict[str, Any]]:
        resource = self.repository.get_resource_by_code(code)
        if resource is None or str(resource["resource_kind"]) != "loki":
            raise _discovery_error("未找到 Loki Resource")
        draft = self.repository.get_draft(str(resource["id"]))
        if str(draft["provider_type"]) != "loki":
            raise _discovery_error("Loki Resource Draft Provider 无效")
        return resource, draft

    def _require_session(
        self,
        *,
        session_id: str,
        resource: dict[str, Any],
        draft: dict[str, Any],
        actor_id: str,
    ) -> None:
        row = self.repository.database.execute_one(
            """
            select * from loki_resource_draft_test_session
             where id = ? and resource_id = ? and draft_id = ?
               and draft_revision = ? and content_hash = ?
               and actor_id = ? and status = 'ACTIVE' and expires_at > ?
            """,
            (
                session_id,
                resource["id"],
                draft["id"],
                int(draft["draft_revision"]),
                draft["content_hash"],
                actor_id,
                datetime.now(UTC).isoformat(),
            ),
        )
        if row is None:
            raise _session_error("Loki 测试会话无效、已过期或 Draft 已变化")

    def _require_admin(self, actor_id: str) -> None:
        self.permission_service.require_action(
            user_id=actor_id,
            resource_type="platform_config",
            resource_code="*",
            action="manage",
        )


def normalize_exact_conditions(raw: object) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict) or len(raw) > _MAX_CONDITIONS:
        raise _discovery_error("Loki 标签发现条件必须是有界 exact key/value 对象")
    normalized: dict[str, str] = {}
    for key, value in raw.items():
        label = _label_key(str(key))
        text = str(value)
        if (
            not text
            or text != text.strip()
            or len(text) > 256
            or any(ord(character) < 32 for character in text)
            or any(fragment in text for fragment in _FORBIDDEN_EXACT_VALUE_FRAGMENTS)
        ):
            raise _discovery_error("Loki 标签发现只允许精确、非空的 label value")
        normalized[label] = text
    return dict(sorted(normalized.items()))


def _label_key(value: str) -> str:
    text = str(value or "").strip()
    if _LABEL_KEY.fullmatch(text) is None:
        raise _discovery_error("Loki label key 无效")
    return text


def _minutes(value: int, draft: dict[str, Any]) -> int:
    maximum = min(_MAX_DISCOVERY_MINUTES, int(draft["config"]["max_minutes"]))
    if int(value) < 1 or int(value) > maximum:
        raise _discovery_error("Loki 标签发现时间窗超过上限")
    return int(value)


def _limit(value: int, maximum: int) -> int:
    if int(value) < 1 or int(value) > maximum:
        raise _discovery_error("Loki 标签发现数量超过上限")
    return int(value)


def _bounded_strings(values: list[str], *, limit: int) -> tuple[list[str], bool]:
    unique = sorted({str(value) for value in values})
    bounded: list[str] = []
    used_bytes = 2
    for value in unique:
        encoded_bytes = len(json.dumps(value, ensure_ascii=False).encode("utf-8")) + 1
        if len(bounded) >= limit or used_bytes + encoded_bytes > _MAX_DISCOVERY_BYTES:
            return bounded, True
        bounded.append(value)
        used_bytes += encoded_bytes
    return bounded, False


def _exact_selector(conditions: dict[str, str]) -> str:
    return (
        "{"
        + ",".join(
            f"{key}={json.dumps(value, ensure_ascii=False)}"
            for key, value in sorted(conditions.items())
        )
        + "}"
    )


def _discovery_error(safe_message: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        safe_message,
        safe_message=safe_message,
        error_code="loki_draft_discovery_invalid",
    )


def _session_error(safe_message: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        safe_message,
        safe_message=safe_message,
        error_code="loki_draft_test_session_stale",
    )
