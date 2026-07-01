from __future__ import annotations

from typing import Any, Protocol

from ..domain.addressing import ResourceBinding
from ..domain.errors import ResolutionError, UpstreamUnavailable
from ..domain.results import ToolResponse


class RedisGateway(Protocol):
    def get(self, binding: ResourceBinding, key: str) -> ToolResponse: ...

    def scan(self, binding: ResourceBinding, pattern: str, limit: int) -> ToolResponse: ...


class FakeRedisGateway:
    def __init__(self, values: dict[str, str] | None = None, keys: list[str] | None = None) -> None:
        self._values = values or {}
        self._keys = keys or []
        self.calls: list[tuple[str, str]] = []

    def get(self, binding: ResourceBinding, key: str) -> ToolResponse:
        self.calls.append(("get", key))
        return ToolResponse(summary={"key": key, "value_summary": self._values.get(key, None)})

    def scan(self, binding: ResourceBinding, pattern: str, limit: int) -> ToolResponse:
        self.calls.append(("scan", pattern))
        matched = [k for k in self._keys if k.startswith(pattern.rstrip("*"))][:limit]
        return ToolResponse(summary={"pattern": pattern, "keys": matched})


class RealRedisGateway:
    def _connect(self, binding: ResourceBinding) -> Any:
        if binding.redis is None:
            raise ResolutionError("Base has no redis connection configured")
        try:
            import redis
        except ModuleNotFoundError as exc:  # pragma: no cover - driver optional
            raise UpstreamUnavailable("Redis driver is not installed") from exc
        try:
            return redis.Redis(
                host=binding.redis.host,
                port=binding.redis.port,
                db=binding.redis.db,
                password=binding.redis.password or None,
                socket_timeout=5,
                decode_responses=True,
            )
        except Exception as exc:  # pragma: no cover - needs live redis
            raise UpstreamUnavailable(f"Redis connection failed: {type(exc).__name__}") from exc

    def get(self, binding: ResourceBinding, key: str) -> ToolResponse:  # pragma: no cover
        client = self._connect(binding)
        try:
            value = client.get(key)
        except Exception as exc:
            raise UpstreamUnavailable(f"Redis GET failed: {type(exc).__name__}") from exc
        return ToolResponse(summary={"key": key, "value_summary": value})

    def scan(
        self, binding: ResourceBinding, pattern: str, limit: int
    ) -> ToolResponse:  # pragma: no cover
        client = self._connect(binding)
        try:
            cursor, keys = client.scan(cursor=0, match=pattern, count=limit)
        except Exception as exc:
            raise UpstreamUnavailable(f"Redis SCAN failed: {type(exc).__name__}") from exc
        return ToolResponse(summary={"pattern": pattern, "keys": list(keys)[:limit]})
