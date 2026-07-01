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
    RedisConnection,
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


def _build_database(data: dict[str, Any], resolver: SecretResolver) -> DatabaseConnection:
    return DatabaseConnection(
        host=_value(data, "host", resolver),
        port=int(data.get("port", 0)),
        database=_value(data, "database", resolver),
        user=_value(data, "user", resolver),
        password=_value(data, "password", resolver),
    )


def _build_redis(data: dict[str, Any], resolver: SecretResolver) -> RedisConnection:
    return RedisConnection(
        host=_value(data, "host", resolver),
        port=int(data.get("port", 6379)),
        db=int(data.get("db", 0)),
        password=_value(data, "password", resolver),
    )


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
