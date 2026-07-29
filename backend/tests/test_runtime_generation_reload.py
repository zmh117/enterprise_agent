from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

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
from app.modules.job.application.create_agent_job_service import (
    CreateAgentJobCommand,
)
from app.modules.platform_config.application.runtime_generation import (
    GovernedRuntimeGenerationBuilder,
    PublishedRuntimeGenerationReloader,
)
from app.modules.platform_config.application.snapshot import (
    PlatformTopologySnapshotBuilder,
)
from app.modules.platform_config.infrastructure.repository import (
    PlatformConfigRepository,
)
from app.modules.platform_config.infrastructure.runtime_generation_repository import (
    RuntimeGenerationRepository,
)
from backend.tests.test_governed_job_execution_scope import (
    _governed_application,
)
from app.shared.exceptions import NonRetryableExecutionError
import pytest


def _generation_runtime() -> tuple[
    object,
    PlatformService,
    PublishedRuntimeGenerationReloader,
    dict[str, object],
    dict[str, object],
]:
    runtime, publication, resource_revision = (
        _governed_application()
    )
    config_repository = PlatformConfigRepository(runtime.database)
    initial = PlatformTopologySnapshotBuilder(
        config_repository
    ).build_runtime_snapshot()
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
    repository = RuntimeGenerationRepository(runtime.database)
    reloader = PublishedRuntimeGenerationReloader(
        repository,
        GovernedRuntimeGenerationBuilder(
            repository,
            config_repository,
            resolver=DbBackedSecretResolver(
                config_repository,
                master_key=runtime.settings.app_config_master_key,
            ),
        ),
        platform,
    )
    return (
        runtime,
        platform,
        reloader,
        publication,
        resource_revision,
    )


def test_published_generation_is_complete_atomic_and_draft_is_not_effective() -> None:
    runtime, platform, reloader, _publication, revision = (
        _generation_runtime()
    )
    try:
        first = reloader.poll_once(force=True)
        assert first.activated is True
        captured = platform.capture_runtime_snapshot()
        assert captured.generation_no == 1
        assert captured.published_digest
        assert captured.effective_digest
        assert len(captured.resource_states) == 1
        assert captured.resource_states[0]["status"] == "READY"

        target = TargetRef(
            environment="local",
            base="governed-base",
            workshop=None,
            kind=ResourceKind.DATABASE,
        )
        old_registry_generation = platform._registry.capture()  # noqa: SLF001
        old_binding = platform._registry.resolve_revision(  # noqa: SLF001
            target,
            resource_revision_id=str(revision["id"]),
            generation=old_registry_generation,
        )
        assert old_binding.database is not None
        assert old_binding.database.password == (
            "governed-scope-password"
        )

        resources = runtime.platform_config_service.governed_resources
        draft = resources.create_draft_from_revision(
            "governed_scope_mysql",
            str(revision["id"]),
            actor_id="local-user",
        )
        resources.save_draft(
            "governed_scope_mysql",
            {
                "provider_type": "mysql",
                "config": {
                    **draft["config"],
                    "database": "draft-only",
                },
                "secret_refs": draft["secret_refs"],
            },
            expected_revision=int(draft["draft_revision"]),
            actor_id="local-user",
        )
        unchanged = reloader.poll_once()
        assert unchanged.observed is False
        assert platform.capture_runtime_snapshot() is captured

        runtime.platform_config_service.rotate_platform_secret(
            "governed_scope_mysql_password",
            {"value": "governed-scope-password-v2"},
            actor_id="local-user",
        )
        second = reloader.poll_once()
        assert second.activated is True
        assert second.generation_no == 2
        new_binding = platform._registry.resolve_revision(  # noqa: SLF001
            target,
            resource_revision_id=str(revision["id"]),
        )
        assert new_binding.database is not None
        assert new_binding.database.password == (
            "governed-scope-password-v2"
        )
        still_old = platform._registry.resolve_revision(  # noqa: SLF001
            target,
            resource_revision_id=str(revision["id"]),
            generation=old_registry_generation,
        )
        assert still_old.database is not None
        assert still_old.database.password == (
            "governed-scope-password"
        )
    finally:
        runtime.database.close()


def test_failed_reload_keeps_lkg_and_marks_only_dependent_application_degraded() -> None:
    runtime, platform, reloader, _publication, revision = (
        _generation_runtime()
    )
    try:
        first = reloader.poll_once(force=True)
        assert first.activated is True
        runtime.platform_config_service.disable_platform_secret(
            "governed_scope_mysql_password",
            actor_id="local-user",
        )
        second = reloader.poll_once()
        assert second.activated is True
        assert second.retained_lkg is True
        snapshot = platform.capture_runtime_snapshot()
        assert snapshot.resource_states[0]["status"] == "DEGRADED"
        assert snapshot.resource_states[0][
            "effective_revision_id"
        ] == str(revision["id"])
        assert snapshot.application_states[0]["status"] == "DEGRADED"
        assert snapshot.application_states[0]["reason_codes"] == [
            "resource_lkg_retained"
        ]
        status = platform.config_status()
        assert "governed-scope-password" not in str(status)

        persisted = RuntimeGenerationRepository(
            runtime.database
        ).latest_states()
        assert persisted["generation"]["status"] == "ACTIVE"
        assert persisted["resources"][0]["status"] == "DEGRADED"
        assert (
            persisted["applications"][0]["status"] == "DEGRADED"
        )
    finally:
        runtime.database.close()


def test_concurrent_poll_activates_one_complete_generation() -> None:
    runtime, platform, reloader, _publication, _revision = (
        _generation_runtime()
    )
    try:
        first = reloader.poll_once(force=True)
        assert first.generation_no == 1
        runtime.platform_config_service.rotate_platform_secret(
            "governed_scope_mysql_password",
            {"value": "concurrent-generation-v2"},
            actor_id="local-user",
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(lambda _index: reloader.poll_once(), range(2))
            )
        assert sum(result.activated for result in results) == 1
        snapshot = platform.capture_runtime_snapshot()
        assert snapshot.generation_no == 2
        row = runtime.database.execute_one(
            """
            select count(*) as count
              from runtime_snapshot_generation
             where status = 'ACTIVE'
            """
        )
        assert row == {"count": 1}
    finally:
        runtime.database.close()


def test_missing_resource_without_lkg_blocks_only_bound_application() -> None:
    runtime, platform, reloader, publication, _revision = (
        _generation_runtime()
    )
    try:
        runtime.platform_config_service.disable_platform_secret(
            "governed_scope_mysql_password",
            actor_id="local-user",
        )
        result = reloader.poll_once(force=True)
        assert result.activated is True
        snapshot = platform.capture_runtime_snapshot()
        assert snapshot.resource_states[0]["status"] == "BLOCKED"
        assert snapshot.application_states[0]["status"] == "BLOCKED"
        assert snapshot.revision_resources == {}
        assert snapshot.errors == []
        assert platform.config_status()["valid"] is True
        public = runtime.platform_config_service.public_snapshot()
        assert public["governed_runtime"]["status"] == "BLOCKED"
        assert "governed-scope-password" not in str(public)
        with pytest.raises(
            NonRetryableExecutionError,
            match="runtime is blocked",
        ):
            runtime.create_agent_job_service.execute(
                CreateAgentJobCommand(
                    idempotency_key="blocked-runtime-job",
                    user_message="不应创建",
                    requester_id="user_local_admin",
                    business_application_publication_id=str(
                        publication["id"]
                    ),
                )
            )
    finally:
        runtime.database.close()
