from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any
from urllib.request import urlopen

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.modules.platform_config.application.snapshot import RuntimeTopologySnapshot
from app.modules.platform_config.application.snapshot import PlatformTopologySnapshotBuilder
from app.modules.platform_config.application.secret_reload import (
    build_secret_change_reloader,
)
from app.modules.platform_config.application.runtime_generation import (
    GovernedRuntimeGenerationBuilder,
    PublishedRuntimeGenerationReloader,
)
from app.modules.platform_config.infrastructure import PlatformConfigRepository
from app.modules.platform_config.infrastructure.runtime_generation_repository import (
    RuntimeGenerationRepository,
)
from app.shared.config import Settings, load_settings
from app.shared.database import Database, default_migrations_dir
from app.shared.master_key import load_master_key_settings
from app.shared.migrations import SchemaHeadError, SchemaHeadValidator
from app.shared.runtime_config_loader import load_settings_with_db_overlay
from app.shared.service_token import ServiceTokenSet

from .application.platform_service import PlatformService
from .domain.access import AccessPolicy
from .domain.topology import DatabaseEngine, Topology
from .api.routes import register_routes
from .infrastructure.config import load_platform_config
from .infrastructure.db.drivers import MysqlExecutor, OracleExecutor, SqlServerExecutor
from .infrastructure.db.executor import QueryExecutor
from .infrastructure.db.oracle_client import ensure_oracle_client_initialized
from .infrastructure.db.schema_directory import (
    MySqlSchemaInspector,
    OracleSchemaInspector,
    SchemaInspectorFactory,
    SqlServerSchemaInspector,
)
from .infrastructure.loki_gateway import HttpLokiClient
from .infrastructure.job_authorization import BusinessApplicationJobAccessAuthorizer
from .infrastructure.redis_gateway import RealRedisGateway
from .infrastructure.registry import TopologyRegistry
from .infrastructure.secrets import DbBackedSecretResolver


_logger = logging.getLogger(__name__)


def default_executors(
    *,
    max_response_bytes: int = 1024 * 1024,
) -> dict[DatabaseEngine, QueryExecutor]:
    return {
        DatabaseEngine.MYSQL: MysqlExecutor(
            max_response_bytes=max_response_bytes
        ),
        DatabaseEngine.SQLSERVER: SqlServerExecutor(
            max_response_bytes=max_response_bytes
        ),
        DatabaseEngine.ORACLE: OracleExecutor(
            max_response_bytes=max_response_bytes
        ),
    }


def _bootstrap_oracle_client() -> None:
    """Best-effort thick init at process start when Instant Client is present."""

    ensure_oracle_client_initialized()


def default_schema_inspector_factory() -> SchemaInspectorFactory:
    return SchemaInspectorFactory(
        {
            DatabaseEngine.MYSQL: MySqlSchemaInspector(),
            DatabaseEngine.SQLSERVER: SqlServerSchemaInspector(),
            DatabaseEngine.ORACLE: OracleSchemaInspector(),
        }
    )


def build_service(
    settings: Settings,
    *,
    urlopen_func: Callable[..., Any] = urlopen,
) -> PlatformService:
    _bootstrap_oracle_client()
    settings = load_settings_with_db_overlay(
        settings,
        service_name="internal-api-platform",
    )
    snapshot = _load_topology_snapshot(settings)
    job_authorization_database = Database(settings.database_dsn)
    job_access_authorizer = BusinessApplicationJobAccessAuthorizer(
        job_authorization_database
    )
    service = PlatformService(
        registry=TopologyRegistry(snapshot.topology),
        access_policy=snapshot.access_policy,
        executors=default_executors(
            max_response_bytes=(
                settings.internal_platform_max_response_bytes
            )
        ),
        schema_inspector_factory=default_schema_inspector_factory(),
        redis_gateway=RealRedisGateway(),
        loki_client=HttpLokiClient(
            max_minutes=settings.loki.max_minutes,
            max_lines=settings.loki.max_lines,
            max_response_chars=settings.loki.max_response_chars,
            urlopen_func=urlopen_func,
        ),
        max_rows=settings.internal_platform_max_rows,
        query_timeout_seconds=settings.internal_api_timeout_seconds,
        max_response_bytes=settings.internal_platform_max_response_bytes,
        redis_scan_limit=settings.execution.redis_scan_limit,
        config_source=snapshot.source,
        config_revision=snapshot.revision,
        config_hash=snapshot.config_hash,
        config_errors=snapshot.errors,
        config_resource_count=snapshot.resource_count,
        job_access_authorizer=job_access_authorizer,
    )
    reload_database = Database(settings.database_dsn)
    if _runtime_generation_schema_available(reload_database):
        config_repository = PlatformConfigRepository(reload_database)
        generation_repository = RuntimeGenerationRepository(
            reload_database
        )
        service.attach_runtime_generation_reloader(
            PublishedRuntimeGenerationReloader(
                generation_repository,
                GovernedRuntimeGenerationBuilder(
                    generation_repository,
                    config_repository,
                    resolver=DbBackedSecretResolver(
                        config_repository,
                        master_key=settings.app_config_master_key,
                    ),
                ),
                service,
            )
        )
    else:
        service.attach_secret_change_reloader(
            build_secret_change_reloader(
                database=reload_database,
                master_key=settings.app_config_master_key,
                target=service,
            )
        )
    return service


def _load_topology_snapshot(settings: Settings) -> RuntimeTopologySnapshot:
    config_path = os.getenv("INTERNAL_PLATFORM_TOPOLOGY_FILE", "")
    try:
        database = Database(settings.database_dsn)
        try:
            repository = PlatformConfigRepository(database)
            snapshot = PlatformTopologySnapshotBuilder(
                repository,
                resolver=DbBackedSecretResolver(
                    repository,
                    master_key=settings.app_config_master_key,
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
    settings = load_master_key_settings(settings or load_settings())
    service_tokens = ServiceTokenSet.from_file(
        settings.internal_api_auth_token_file,
        required=settings.environment not in {"test", "testing"},
    )
    service = service or build_service(settings, urlopen_func=urlopen_func)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        reload_task = asyncio.create_task(
            _poll_runtime_changes(service)
        )
        try:
            yield
        finally:
            reload_task.cancel()
            with suppress(asyncio.CancelledError):
                await reload_task
            service.close()

    app = FastAPI(
        title="Internal API Platform",
        version="1.0.0",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def authenticate_internal_tools(
        request: Request,
        call_next: Callable[[Request], Any],
    ) -> Any:
        if (
            request.url.path.startswith("/tools/")
            and service_tokens is not None
            and not service_tokens.matches_bearer_header(
                request.headers.get("authorization", "")
            )
        ):
            return JSONResponse(
                status_code=401,
                content={"detail": "内部服务认证失败"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)

    register_routes(app, service=service)

    @app.get("/ready")
    async def ready() -> dict[str, Any]:
        database = Database(settings.database_dsn)
        try:
            database_ready = database.ping()
            schema_ready = False
            schema_head = ""
            if database_ready:
                try:
                    schema_head = SchemaHeadValidator(
                        database,
                        default_migrations_dir(),
                    ).require_current()
                    schema_ready = True
                except SchemaHeadError:
                    schema_ready = False
            token_ready = (
                service_tokens is not None
                or settings.environment in {"test", "testing"}
            )
            master_key_ready = bool(settings.app_config_master_key)
            core_ready = all(
                (
                    database_ready,
                    schema_ready,
                    token_ready,
                    master_key_ready,
                )
            )
            status = {
                "status": (
                    "ready" if core_ready else "not_ready"
                ),
                "core": {
                    "database": database_ready,
                    "schema": schema_ready,
                    "schema_head": schema_head,
                    "internal_api_token": token_ready,
                    "master_key": master_key_ready,
                    "runtime_assembly": True,
                },
                "resources": service.config_status(),
                "model_invoked": False,
            }
        finally:
            database.close()
        if not core_ready:
            raise HTTPException(status_code=503, detail=status)
        return status
    return app


async def _poll_runtime_changes(service: PlatformService) -> None:
    while True:
        try:
            await asyncio.to_thread(service.poll_secret_changes)
            await asyncio.to_thread(service.poll_runtime_generation)
        except Exception:
            _logger.exception(
                "Runtime generation reload poll failed",
            )
        await asyncio.sleep(1)


def _runtime_generation_schema_available(database: Database) -> bool:
    if database.engine == "sqlite":
        row = database.execute_one(
            """
            select name
              from sqlite_master
             where type = 'table'
               and name = 'runtime_snapshot_generation'
            """
        )
    else:
        row = database.execute_one(
            """
            select table_name
              from information_schema.tables
             where table_schema = current_schema()
               and table_name = 'runtime_snapshot_generation'
            """
        )
    return row is not None
