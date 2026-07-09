from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..domain.access import AccessPolicy, AccessScope, ScopeRule
from ..domain.topology import (
    Base,
    DatabaseConnection,
    DatabaseEngine,
    Environment,
    LokiConnection,
    OracleClientMode,
    OracleCompat,
    RedisConnection,
    RedisMode,
    RedisNode,
    Topology,
    Workshop,
)
from .secrets import EnvSecretResolver, SecretResolver


class TopologyConfigError(Exception):
    pass


def _value(data: dict[str, Any], key: str, resolver: SecretResolver, default: str = "") -> str:
    if key in data:
        return str(data[key])
    ref_key = f"{key}_ref"
    if ref_key in data:
        return resolver.resolve(str(data[ref_key]))
    return default


def _parse_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    raise TopologyConfigError(f"Invalid boolean value: {value}")


def _parse_redis_mode(value: Any) -> RedisMode:
    text = str(value or RedisMode.STANDALONE.value).strip().lower()
    try:
        return RedisMode(text)
    except ValueError as exc:
        raise TopologyConfigError(
            f"Invalid redis mode '{value}'; expected standalone or cluster"
        ) from exc


def _parse_oracle_client_mode(value: Any) -> OracleClientMode:
    text = str(value or OracleClientMode.AUTO.value).strip().lower()
    try:
        return OracleClientMode(text)
    except ValueError as exc:
        raise TopologyConfigError(
            f"Invalid oracle_client_mode '{value}'; expected thin, thick, or auto"
        ) from exc


def _parse_oracle_compat(value: Any) -> OracleCompat:
    text = str(value or OracleCompat.MODERN.value).strip().lower()
    try:
        return OracleCompat(text)
    except ValueError as exc:
        raise TopologyConfigError(
            f"Invalid oracle_compat '{value}'; expected modern or legacy"
        ) from exc


def _parse_redis_nodes(data: dict[str, Any], resolver: SecretResolver) -> tuple[RedisNode, ...]:
    raw_nodes = data.get("nodes")
    if not raw_nodes:
        return ()
    if not isinstance(raw_nodes, list):
        raise TopologyConfigError("redis.nodes must be a list")
    nodes: list[RedisNode] = []
    for index, item in enumerate(raw_nodes):
        if not isinstance(item, dict):
            raise TopologyConfigError(f"redis.nodes[{index}] must be an object")
        host = _value(item, "host", resolver)
        if not host:
            raise TopologyConfigError(f"redis.nodes[{index}].host is required")
        nodes.append(RedisNode(host=host, port=int(item.get("port", 6379))))
    return tuple(nodes)


def validate_redis_connection(conn: RedisConnection) -> None:
    if conn.mode is RedisMode.CLUSTER:
        if not conn.startup_nodes():
            raise TopologyConfigError(
                "Redis cluster mode requires startup nodes (nodes list or host)"
            )
        if conn.db not in (0, None):
            # Cluster has no SELECT db; non-zero is a misconfiguration.
            if int(conn.db) != 0:
                raise TopologyConfigError(
                    "Redis cluster mode does not support non-zero db; omit db or set db: 0"
                )


def _build_database(data: dict[str, Any], resolver: SecretResolver) -> DatabaseConnection:
    return DatabaseConnection(
        host=_value(data, "host", resolver),
        port=int(data.get("port", 0)),
        database=_value(data, "database", resolver),
        user=_value(data, "user", resolver),
        password=_value(data, "password", resolver),
        schema=str(data.get("schema") or ""),
        oracle_client_mode=_parse_oracle_client_mode(data.get("oracle_client_mode")),
        oracle_compat=_parse_oracle_compat(data.get("oracle_compat")),
        use_sid=_parse_bool(data.get("use_sid"), default=False),
        connect_descriptor=str(data.get("connect_descriptor") or ""),
    )


def _build_redis(data: dict[str, Any], resolver: SecretResolver) -> RedisConnection:
    mode = _parse_redis_mode(data.get("mode"))
    nodes = _parse_redis_nodes(data, resolver)
    host = _value(data, "host", resolver)
    port = int(data.get("port", 6379))
    if mode is RedisMode.CLUSTER and not host and nodes:
        host = nodes[0].host
        port = nodes[0].port
    conn = RedisConnection(
        host=host,
        port=port,
        db=int(data.get("db", 0)),
        password=_value(data, "password", resolver),
        mode=mode,
        nodes=nodes,
    )
    validate_redis_connection(conn)
    return conn


def _build_loki(data: dict[str, Any], resolver: SecretResolver) -> LokiConnection:
    return LokiConnection(
        base_url=_value(data, "base_url", resolver),
        tenant=str(data.get("tenant", "")),
    )


def _aliases(data: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(item) for item in (data.get("aliases") or []))


def _build_workshop(code: str, data: dict[str, Any]) -> Workshop:
    return Workshop(
        code=code,
        table_prefix=str(data.get("table_prefix", "")),
        redis_key_prefix=str(data.get("redis_key_prefix", "")),
        loki_label=dict(data.get("loki_label", {})),
        display_name=str(data.get("display_name", "")),
        aliases=_aliases(data),
    )


def _build_base(code: str, data: dict[str, Any], resolver: SecretResolver) -> Base:
    try:
        engine = DatabaseEngine(str(data["engine"]))
    except (KeyError, ValueError) as exc:
        raise TopologyConfigError(f"Base '{code}' has an invalid or missing engine") from exc
    workshops = {
        ws_code: _build_workshop(ws_code, ws_data or {})
        for ws_code, ws_data in (data.get("workshops") or {}).items()
    }
    return Base(
        code=code,
        engine=engine,
        database=_build_database(data["database"], resolver) if data.get("database") else None,
        redis=_build_redis(data["redis"], resolver) if data.get("redis") else None,
        loki=_build_loki(data["loki"], resolver) if data.get("loki") else None,
        workshops=workshops,
        display_name=str(data.get("display_name", "")),
        aliases=_aliases(data),
    )


def build_topology(data: dict[str, Any], resolver: SecretResolver) -> Topology:
    environments: dict[str, Environment] = {}
    for env_code, env_data in (data.get("environments") or {}).items():
        bases = {
            base_code: _build_base(base_code, base_data or {}, resolver)
            for base_code, base_data in (env_data.get("bases") or {}).items()
        }
        environments[env_code] = Environment(
            code=env_code,
            bases=bases,
            display_name=str(env_data.get("display_name", "")),
            aliases=_aliases(env_data),
        )
    return Topology(environments=environments)


def build_access_policy(data: dict[str, Any]) -> AccessPolicy:
    scopes: dict[str, AccessScope] = {}
    for user_id, grants in (data.get("access") or {}).items():
        rules = [
            ScopeRule(
                environment=str(grant.get("environment", "*")),
                base=str(grant.get("base", "*")),
                workshop=str(grant.get("workshop", "*")),
            )
            for grant in (grants or [])
        ]
        scopes[user_id] = AccessScope(rules=rules)
    return AccessPolicy(scopes=scopes)


def load_platform_config(
    path: str | Path,
    *,
    resolver: SecretResolver | None = None,
) -> tuple[Topology, AccessPolicy]:
    resolver = resolver or EnvSecretResolver()
    raw = yaml.safe_load(Path(path).read_text()) or {}
    if not isinstance(raw, dict):
        raise TopologyConfigError("Topology config root must be a mapping")
    return build_topology(raw, resolver), build_access_policy(raw)
