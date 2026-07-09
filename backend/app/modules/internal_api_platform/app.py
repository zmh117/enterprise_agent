from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any
from urllib.request import urlopen

from fastapi import FastAPI

from app.shared.config import Settings, load_settings
from app.shared.database import Database, default_migrations_dir
from app.modules.platform_config.application.snapshot import RuntimeTopologySnapshot
from app.modules.platform_config.application.snapshot import PlatformTopologySnapshotBuilder
from app.modules.platform_config.infrastructure import PlatformConfigRepository
from app.shared.runtime_config_loader import load_settings_with_db_overlay

from .application.platform_service import PlatformService
from .domain.access import AccessPolicy
from .domain.schema_directory import SchemaDirectoryReader
from .domain.topology import DatabaseEngine, Topology
from .api.routes import register_routes
from .infrastructure.config import load_platform_config
from .infrastructure.db.drivers import MysqlExecutor, OracleExecutor, SqlServerExecutor
from .infrastructure.db.executor import QueryExecutor
from .infrastructure.db.oracle_client import ensure_oracle_client_initialized
from .infrastructure.db.schema_directory import (
    MySqlSchemaDirectoryReader,
    UnsupportedSchemaDirectoryReader,
)
from .infrastructure.loki_gateway import HttpLokiClient
from .infrastructure.redis_gateway import RealRedisGateway
from .infrastructure.registry import TopologyRegistry
from .infrastructure.secrets import DbBackedSecretResolver


def default_executors() -> dict[DatabaseEngine, QueryExecutor]:
    return {
        DatabaseEngine.MYSQL: MysqlExecutor(),
        DatabaseEngine.SQLSERVER: SqlServerExecutor(),
        DatabaseEngine.ORACLE: OracleExecutor(),
    }


def _bootstrap_oracle_client() -> None:
    """Best-effort thick init at process start when Instant Client is present."""

    ensure_oracle_client_initialized()


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
    _bootstrap_oracle_client()
    settings = load_settings_with_db_overlay(
        settings,
        service_name="internal-api-platform",
        migrate=settings.app_startup_migrate,
    )
    snapshot = _load_topology_snapshot(settings)
    return PlatformService(
        registry=TopologyRegistry(snapshot.topology),
        access_policy=snapshot.access_policy,
        executors=default_executors(),
        schema_readers=default_schema_readers(),
        redis_gateway=RealRedisGateway(),
        loki_client=HttpLokiClient(
            max_minutes=settings.loki.max_minutes,
            max_lines=settings.loki.max_lines,
            max_response_chars=settings.loki.max_response_chars,
            urlopen_func=urlopen_func,
        ),
        max_rows=settings.internal_platform_max_rows,
        query_timeout_seconds=settings.internal_api_timeout_seconds,
        redis_scan_limit=settings.execution.redis_scan_limit,
        config_source=snapshot.source,
        config_revision=snapshot.revision,
        config_hash=snapshot.config_hash,
        config_errors=snapshot.errors,
        config_resource_count=snapshot.resource_count,
    )


def _load_topology_snapshot(settings: Settings) -> RuntimeTopologySnapshot:
    config_path = os.getenv("INTERNAL_PLATFORM_TOPOLOGY_FILE", "")
    try:
        database = Database(settings.database_dsn)
        try:
            if settings.app_startup_migrate:
                database.run_migrations(default_migrations_dir())
            repository = PlatformConfigRepository(database)
            snapshot = PlatformTopologySnapshotBuilder(
                repository,
                resolver=DbBackedSecretResolver(
                    repository,
                    master_key=os.getenv("APP_CONFIG_MASTER_KEY", ""),
                ),
            ).build_runtime_snapshot()
        finally:
            database.close()
        if snapshot.source == "database":
            return snapshot
        if snapshot.source == "database-invalid":
            return snapshot
        if not config_path:
            return snapshot
    except Exception as exc:
        if not config_path:
            return RuntimeTopologySnapshot(
                topology=Topology(),
                access_policy=AccessPolicy(),
                source="database-error",
                revision=0,
                config_hash="",
                resource_count=0,
                errors=[str(exc)],
            )
    topology, access_policy = load_platform_config(config_path)
    return RuntimeTopologySnapshot(
        topology=topology,
        access_policy=access_policy,
        source="yaml",
        revision=0,
        config_hash="",
        resource_count=sum(
            int(base.database is not None)
            + int(base.redis is not None)
            + int(base.loki is not None)
            for environment in topology.environments.values()
            for base in environment.bases.values()
        ),
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
