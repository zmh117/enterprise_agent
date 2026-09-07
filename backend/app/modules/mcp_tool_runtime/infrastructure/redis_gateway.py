from __future__ import annotations

from typing import Any, Protocol

from app.shared.database import assert_external_io_allowed

from ..domain.addressing import ResourceBinding
from ..domain.errors import PolicyViolation, ResolutionError, UpstreamUnavailable
from ..domain.results import ToolResponse
from ..domain.topology import RedisMode


class RedisGateway(Protocol):
    def get(self, binding: ResourceBinding, key: str) -> ToolResponse: ...

    def scan(
        self,
        binding: ResourceBinding,
        pattern: str,
        limit: int,
        cursor: object = 0,
    ) -> ToolResponse: ...


class FakeRedisGateway:
    def __init__(self, values: dict[str, str] | None = None, keys: list[str] | None = None) -> None:
        self._values = values or {}
        self._keys = keys or []
        self.calls: list[tuple[str, str]] = []

    def get(self, binding: ResourceBinding, key: str) -> ToolResponse:
        self.calls.append(("get", key))
        return ToolResponse(summary={"key": key, "value_summary": self._values.get(key, None)})

    def scan(
        self,
        binding: ResourceBinding,
        pattern: str,
        limit: int,
        cursor: object = 0,
    ) -> ToolResponse:
        self.calls.append(("scan", pattern))
        literal_prefix = pattern.rstrip("*").replace("\\[", "[").replace("\\]", "]")
        matched = [k for k in self._keys if k.startswith(literal_prefix)]
        normalized_cursor = _normalize_scan_cursor(cursor)
        if not isinstance(normalized_cursor, int):
            raise PolicyViolation("Fake Redis SCAN does not support a cluster cursor")
        start = normalized_cursor
        page = matched[start : start + limit]
        next_cursor = start + len(page) if start + len(page) < len(matched) else 0
        return ToolResponse(
            summary={"pattern": pattern, "keys": page},
            truncated=bool(next_cursor),
            metadata={"next_provider_cursor": next_cursor},
        )


class RealRedisGateway:
    def _connect(self, binding: ResourceBinding) -> Any:
        if binding.redis is None:
            raise ResolutionError("Base has no redis connection configured")
        try:
            import redis
        except ModuleNotFoundError as exc:  # pragma: no cover - driver optional
            raise UpstreamUnavailable("Redis driver is not installed") from exc

        conn = binding.redis
        try:
            if conn.mode is RedisMode.CLUSTER:
                nodes = conn.startup_nodes()
                if not nodes:
                    raise ResolutionError(
                        "Redis cluster mode requires startup nodes (nodes list or host)"
                    )
                startup_nodes = [{"host": n.host, "port": n.port} for n in nodes]
                try:
                    from redis.cluster import RedisCluster
                except ImportError as exc:  # pragma: no cover - old redis
                    raise UpstreamUnavailable(
                        "Redis Cluster requires redis-py with RedisCluster support"
                    ) from exc
                return RedisCluster(
                    startup_nodes=startup_nodes,
                    username=conn.username or None,
                    password=conn.password or None,
                    socket_timeout=5,
                    socket_connect_timeout=5,
                    ssl=conn.tls_enabled,
                    ssl_cert_reqs=("required" if conn.tls_verify_certificate else None),
                    ssl_check_hostname=conn.tls_verify_certificate,
                    decode_responses=True,
                )
            return redis.Redis(
                host=conn.host,
                port=conn.port,
                db=conn.db,
                username=conn.username or None,
                password=conn.password or None,
                socket_timeout=5,
                socket_connect_timeout=5,
                ssl=conn.tls_enabled,
                ssl_cert_reqs=("required" if conn.tls_verify_certificate else None),
                ssl_check_hostname=(conn.tls_enabled and conn.tls_verify_certificate),
                decode_responses=True,
            )
        except ResolutionError:
            raise
        except Exception as exc:  # pragma: no cover - needs live redis
            raise UpstreamUnavailable(f"Redis connection failed: {type(exc).__name__}") from exc

    def get(self, binding: ResourceBinding, key: str) -> ToolResponse:  # pragma: no cover
        assert_external_io_allowed("tool_redis.get")
        client = self._connect(binding)
        try:
            value = client.get(key)
        except Exception as exc:
            raise UpstreamUnavailable(f"Redis GET failed: {type(exc).__name__}") from exc
        return ToolResponse(summary={"key": key, "value_summary": value})

    def scan(
        self,
        binding: ResourceBinding,
        pattern: str,
        limit: int,
        cursor: object = 0,
    ) -> ToolResponse:  # pragma: no cover
        assert_external_io_allowed("tool_redis.scan")
        # Policy (workshop key prefix / bounded pattern) is enforced in PlatformService
        # before this method; both standalone and cluster clients honor match/count.
        normalized_cursor = _normalize_scan_cursor(cursor)
        client = self._connect(binding)
        try:
            provider_cursor, keys = client.scan(
                cursor=normalized_cursor,
                match=pattern,
                count=limit,
            )
        except Exception as exc:
            raise UpstreamUnavailable(f"Redis SCAN failed: {type(exc).__name__}") from exc
        next_cursor = _normalize_scan_cursor(provider_cursor)
        return ToolResponse(
            summary={"pattern": pattern, "keys": list(keys)[:limit]},
            truncated=not _scan_cursor_complete(next_cursor),
            metadata={"next_provider_cursor": next_cursor},
        )


def _normalize_scan_cursor(value: object) -> int | dict[str, int]:
    if value is None or value == "" or value == b"":
        return 0
    if isinstance(value, bool):
        raise PolicyViolation("Redis SCAN cursor is invalid")
    if isinstance(value, int):
        if value < 0:
            raise PolicyViolation("Redis SCAN cursor is invalid")
        return value
    if isinstance(value, bytes):
        try:
            value = value.decode("ascii")
        except UnicodeDecodeError as exc:
            raise PolicyViolation("Redis SCAN cursor is invalid") from exc
    if isinstance(value, str):
        if not value.isdigit():
            raise PolicyViolation("Redis SCAN cursor is invalid")
        return int(value)
    if isinstance(value, dict) and len(value) <= 256:
        normalized: dict[str, int] = {}
        for raw_node, raw_cursor in value.items():
            node = str(raw_node or "")
            if not node or len(node) > 256:
                raise PolicyViolation("Redis Cluster SCAN cursor is invalid")
            if isinstance(raw_cursor, bool):
                raise PolicyViolation("Redis Cluster SCAN cursor is invalid")
            try:
                parsed = int(raw_cursor)
            except (TypeError, ValueError) as exc:
                raise PolicyViolation("Redis Cluster SCAN cursor is invalid") from exc
            if parsed < 0:
                raise PolicyViolation("Redis Cluster SCAN cursor is invalid")
            normalized[node] = parsed
        return dict(sorted(normalized.items()))
    raise PolicyViolation("Redis SCAN cursor is invalid")


def _scan_cursor_complete(value: int | dict[str, int]) -> bool:
    return value == 0 or (isinstance(value, dict) and all(cursor == 0 for cursor in value.values()))
