from __future__ import annotations

from dataclasses import replace
from typing import Any, Protocol

from app.shared.database import assert_external_io_allowed
from app.shared.exceptions import ToolPolicyError

from ..domain.addressing import ResourceBinding
from ..domain.errors import PolicyViolation, ResolutionError, UpstreamUnavailable
from ..domain.redis_pagination import (
    RedisScanPosition,
    scan_complete,
    scan_fingerprint,
    stale_scan_cursor,
)
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
        position = RedisScanPosition.parse(cursor)
        if position.topology_hash or position.offset:
            raise PolicyViolation("Fake Redis SCAN does not support a cluster cursor")
        start = position.provider_cursor
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
                try:
                    from redis.cluster import ClusterNode, RedisCluster
                except ImportError as exc:  # pragma: no cover - old redis
                    raise UpstreamUnavailable(
                        "Redis Cluster requires redis-py with RedisCluster support"
                    ) from exc
                node_factory: Any = ClusterNode
                return RedisCluster(
                    startup_nodes=[node_factory(n.host, n.port) for n in nodes],
                    username=conn.username or None,
                    password=conn.password or None,
                    socket_timeout=5,
                    socket_connect_timeout=5,
                    ssl=conn.tls_enabled,
                    ssl_cert_reqs=("required" if conn.tls_verify_certificate else "none"),
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
                ssl_cert_reqs=("required" if conn.tls_verify_certificate else "none"),
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
        finally:
            client.close()
        return ToolResponse(summary={"key": key, "value_summary": value})

    def scan(
        self,
        binding: ResourceBinding,
        pattern: str,
        limit: int,
        cursor: object = 0,
    ) -> ToolResponse:  # pragma: no cover
        assert_external_io_allowed("tool_redis.scan")
        # Namespace policy is enforced by the executor before opening any connection.
        position = RedisScanPosition.parse(cursor)
        if type(limit) is not int or limit < 1:
            raise PolicyViolation("Redis 扫描页大小必须为正整数")
        client = self._connect(binding)
        try:
            node_count = 1
            scan_options: dict[str, Any] = {}
            node_name = ""
            if binding.redis is not None and binding.redis.mode is RedisMode.CLUSTER:
                nodes = sorted(client.get_primaries(), key=lambda node: node.name)
                topology_hash = scan_fingerprint([node.name for node in nodes])
                if not nodes:
                    raise UpstreamUnavailable("Redis 集群没有可用主节点")
                if (position.topology_hash and position.topology_hash != topology_hash) or (
                    position.node_index >= len(nodes)
                ):
                    raise stale_scan_cursor()
                position = replace(position, topology_hash=topology_hash)
                node_count = len(nodes)
                node = nodes[position.node_index]
                node_name = node.name
                scan_options["target_nodes"] = node
            elif position.topology_hash:
                raise stale_scan_cursor()
            provider_cursor, keys = client.scan(
                cursor=position.provider_cursor,
                match=pattern,
                count=limit,
                **scan_options,
            )
            if node_name:
                if not isinstance(provider_cursor, dict) or set(provider_cursor) != {node_name}:
                    raise UpstreamUnavailable("Redis 集群返回了无效扫描状态")
                provider_cursor = provider_cursor[node_name]
            next_provider_cursor = _provider_cursor(provider_cursor)
            if not isinstance(keys, (list, tuple)) or any(not isinstance(k, str) for k in keys):
                raise UpstreamUnavailable("Redis 返回了无效扫描结果")
            page, next_position = position.page(
                list(keys), next_cursor=next_provider_cursor, limit=limit, node_count=node_count
            )
        except (ToolPolicyError, UpstreamUnavailable):
            raise
        except Exception as exc:
            raise UpstreamUnavailable(f"Redis SCAN failed: {type(exc).__name__}") from exc
        finally:
            client.close()
        return ToolResponse(
            summary={"pattern": pattern, "keys": page},
            truncated=not scan_complete(next_position),
            metadata={"next_provider_cursor": next_position},
        )


def _provider_cursor(value: object) -> int:
    if isinstance(value, bytes):
        try:
            value = value.decode("ascii")
        except UnicodeDecodeError as exc:
            raise UpstreamUnavailable("Redis 返回了无效扫描状态") from exc
    if isinstance(value, str):
        if not value.isascii() or not value.isdigit() or len(value) > 20:
            raise UpstreamUnavailable("Redis 返回了无效扫描状态")
        value = int(value)
    if type(value) is not int or not 0 <= value < 2**64:
        raise UpstreamUnavailable("Redis 返回了无效扫描状态")
    return value
