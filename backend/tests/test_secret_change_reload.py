from __future__ import annotations

from app.modules.internal_api_platform.application.platform_service import (
    PlatformService,
)
from app.modules.internal_api_platform.domain.addressing import TargetRef
from app.modules.internal_api_platform.domain.topology import (
    DatabaseEngine,
    ResourceKind,
)
from app.modules.internal_api_platform.infrastructure.db.executor import (
    FakeQueryExecutor,
)
from app.modules.internal_api_platform.infrastructure.loki_gateway import (
    FakeLokiClient,
)
from app.modules.internal_api_platform.infrastructure.redis_gateway import (
    FakeRedisGateway,
)
from app.modules.internal_api_platform.infrastructure.registry import (
    TopologyRegistry,
)
from app.modules.internal_api_platform.infrastructure.secrets import (
    DbBackedSecretResolver,
)
from app.modules.platform_config.application.secret_reload import (
    build_secret_change_reloader,
)
from app.modules.platform_config.application.snapshot import (
    PlatformTopologySnapshotBuilder,
)
from app.modules.platform_config.infrastructure import PlatformConfigRepository
from backend.tests.helpers import container


def test_secret_change_reload_is_atomic_and_preserves_last_known_good() -> None:
    runtime = container()
    config_service = runtime.platform_config_service
    secret = config_service.create_platform_secret(
        {
            "code": "reload_password",
            "value": "reload-password-v1",
        },
        actor_id="local-user",
    )
    config_service.upsert_environment(
        {"code": "reload_env"},
        actor_id="local-user",
    )
    config_service.upsert_base(
        {
            "environment_code": "reload_env",
            "code": "reload_base",
            "engine": "mysql",
        },
        actor_id="local-user",
    )
    config_service.upsert_resource_binding(
        {
            "code": "reload_database",
            "scope_type": "base",
            "environment_code": "reload_env",
            "base_code": "reload_base",
            "resource_kind": "database",
            "engine": "mysql",
            "config": {
                "host": "mysql",
                "port": 3306,
                "database": "reload",
                "user": "reader",
            },
            "secret_refs": {"password": secret["secret_ref"]},
        },
        actor_id="local-user",
    )
    repository = PlatformConfigRepository(runtime.database)
    resolver = DbBackedSecretResolver(
        repository,
        master_key=runtime.settings.app_config_master_key,
    )
    initial = PlatformTopologySnapshotBuilder(
        repository,
        resolver=resolver,
    ).build_runtime_snapshot()
    assert initial.valid
    platform = PlatformService(
        registry=TopologyRegistry(initial.topology),
        access_policy=initial.access_policy,
        executors={
            DatabaseEngine.MYSQL: FakeQueryExecutor(),
            DatabaseEngine.SQLSERVER: FakeQueryExecutor(),
            DatabaseEngine.ORACLE: FakeQueryExecutor(),
        },
        redis_gateway=FakeRedisGateway(),
        loki_client=FakeLokiClient(),
        config_source=initial.source,
        config_revision=initial.revision,
        config_hash=initial.config_hash,
        config_resource_count=initial.resource_count,
    )
    reloader = build_secret_change_reloader(
        database=runtime.database,
        master_key=runtime.settings.app_config_master_key,
        target=platform,
    )
    platform.attach_secret_change_reloader(reloader)
    target = TargetRef(
        environment="reload_env",
        base="reload_base",
        kind=ResourceKind.DATABASE,
    )

    assert platform._registry.resolve(target).database.password == "reload-password-v1"  # noqa: SLF001
    assert platform.poll_secret_changes() == {
        "claimed": 1,
        "succeeded": 1,
        "failed": 0,
    }

    config_service.rotate_platform_secret(
        "reload_password",
        {"value": "reload-password-v2"},
        actor_id="local-user",
    )
    assert platform.poll_secret_changes() == {
        "claimed": 1,
        "succeeded": 1,
        "failed": 0,
    }
    assert platform._registry.resolve(target).database.password == "reload-password-v2"  # noqa: SLF001
    lkg = platform.config_status()["last_known_good"]

    config_service.disable_platform_secret(
        "reload_password",
        actor_id="local-user",
    )
    assert platform.poll_secret_changes() == {
        "claimed": 1,
        "succeeded": 0,
        "failed": 1,
    }
    assert platform._registry.resolve(target).database.password == "reload-password-v2"  # noqa: SLF001
    status = platform.config_status()
    assert status["degraded"] is True
    assert status["valid"] is False
    assert status["last_known_good"] == lkg
    assert "reload-password" not in str(status)

    events = repository.list_secret_change_events(secret_id=secret["id"])
    assert [event["status"] for event in events] == [
        "SUCCEEDED",
        "SUCCEEDED",
        "FAILED",
    ]
    assert "reload-password-v1" not in str(events)
    assert "reload-password-v2" not in str(events)
    platform.close()
