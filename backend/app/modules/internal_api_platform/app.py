from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any
from urllib.request import urlopen

from fastapi import FastAPI

from app.shared.config import Settings, load_settings

from .application.platform_service import PlatformService
from .domain.access import AccessPolicy
from .domain.schema_directory import SchemaDirectoryReader
from .domain.topology import DatabaseEngine, Topology
from .api.routes import register_routes
from .infrastructure.config import load_platform_config
from .infrastructure.db.drivers import MysqlExecutor, OracleExecutor, SqlServerExecutor
from .infrastructure.db.executor import QueryExecutor
from .infrastructure.db.schema_directory import (
    MySqlSchemaDirectoryReader,
    UnsupportedSchemaDirectoryReader,
)
from .infrastructure.loki_gateway import HttpLokiClient
from .infrastructure.redis_gateway import RealRedisGateway
from .infrastructure.registry import TopologyRegistry


def default_executors() -> dict[DatabaseEngine, QueryExecutor]:
    return {
        DatabaseEngine.MYSQL: MysqlExecutor(),
        DatabaseEngine.SQLSERVER: SqlServerExecutor(),
        DatabaseEngine.ORACLE: OracleExecutor(),
    }


def default_schema_readers() -> dict[DatabaseEngine, SchemaDirectoryReader]:
    return {
        DatabaseEngine.MYSQL: MySqlSchemaDirectoryReader(),
        DatabaseEngine.SQLSERVER: UnsupportedSchemaDirectoryReader(DatabaseEngine.SQLSERVER),
        DatabaseEngine.ORACLE: UnsupportedSchemaDirectoryReader(DatabaseEngine.ORACLE),
    }


def build_service(
    settings: Settings,
    *,
    urlopen_func: Callable[..., Any] = urlopen,
) -> PlatformService:
    config_path = os.getenv("INTERNAL_PLATFORM_TOPOLOGY_FILE", "")
    if config_path:
        topology, access_policy = load_platform_config(config_path)
    else:
        topology, access_policy = Topology(), AccessPolicy()
    return PlatformService(
        registry=TopologyRegistry(topology),
        access_policy=access_policy,
        executors=default_executors(),
        schema_readers=default_schema_readers(),
        redis_gateway=RealRedisGateway(),
        loki_client=HttpLokiClient(
            max_minutes=settings.loki.max_minutes,
            max_lines=settings.loki.max_lines,
            max_response_chars=settings.loki.max_response_chars,
            urlopen_func=urlopen_func,
        ),
        max_rows=int(os.getenv("INTERNAL_PLATFORM_MAX_ROWS", "100")),
        query_timeout_seconds=settings.internal_api_timeout_seconds,
        redis_scan_limit=settings.execution.redis_scan_limit,
    )


def create_app(
    settings: Settings | None = None,
    *,
    service: PlatformService | None = None,
    urlopen_func: Callable[..., Any] = urlopen,
) -> FastAPI:
    settings = settings or load_settings()
    service = service or build_service(settings, urlopen_func=urlopen_func)
    app = FastAPI(title="Internal API Platform", version="1.0.0")
    register_routes(app, service=service)
    return app
