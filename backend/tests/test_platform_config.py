from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.internal_api_platform.app import (
    _load_topology_snapshot,
    build_service,
    create_app as create_internal_platform_app,
)
from app.modules.internal_api_platform.application.platform_service import PlatformService
from app.modules.internal_api_platform.domain.errors import AuthorizationError, PolicyViolation
from app.modules.internal_api_platform.domain.topology import DatabaseEngine, ResourceKind
from app.modules.internal_api_platform.infrastructure.db.executor import FakeQueryExecutor
from app.modules.internal_api_platform.infrastructure.db.schema_directory import (
    FakeSchemaDirectoryReader,
)
from app.modules.internal_api_platform.infrastructure.loki_gateway import FakeLokiClient
from app.modules.internal_api_platform.infrastructure.redis_gateway import FakeRedisGateway
from app.modules.internal_api_platform.infrastructure.registry import TopologyRegistry
from app.modules.internal_api_platform.infrastructure.secrets import MappingSecretResolver
from app.modules.platform_config.application.snapshot import PlatformTopologySnapshotBuilder
from app.modules.platform_config.infrastructure import PlatformConfigRepository
from app.shared.config import Settings
from app.shared.database import Database, default_migrations_dir
from backend.tests.helpers import container, test_settings as make_settings


def _example_yaml_path() -> Path:
    return (
        Path(__file__).resolve().parents[1] / "config" / "internal_platform_topology.example.yaml"
    )


def _secret_values() -> dict[str, str]:
    return {
        "secret://sanjiu/guanlan/db_host": "mysql.guanlan",
        "secret://sanjiu/guanlan/db_user": "reader",
        "secret://sanjiu/guanlan/db_password": "db-password",
        "secret://sanjiu/guanlan/redis_host": "redis.guanlan",
        "secret://sanjiu/guanlan/loki_url": "http://loki.guanlan:3100",
        "secret://mmk/main/db_host": "mssql.mmk",
        "secret://mmk/main/db_user": "reader",
        "secret://mmk/main/db_password": "mmk-password",
        "secret://mmk/main/redis_host": "redis.mmk",
        "secret://mmk/main/loki_url": "http://loki.mmk:3100",
    }


def _file_database() -> tuple[tempfile.TemporaryDirectory[str], Database, str]:
    tmp = tempfile.TemporaryDirectory()
    db_path = Path(tmp.name) / "platform.db"
    dsn = f"sqlite:///{db_path}"
    database = Database(dsn)
    database.run_migrations(default_migrations_dir())
    return tmp, database, dsn


def _import_example_to_file_database() -> tuple[tempfile.TemporaryDirectory[str], str]:
    tmp, database, dsn = _file_database()
    from app.modules.platform_config.application.importer import PlatformTopologyYamlImporter

    PlatformTopologyYamlImporter(PlatformConfigRepository(database)).import_file(
        _example_yaml_path(),
        actor_id="local-user",
    )
    database.close()
    return tmp, dsn


def _db_backed_service(
    database: Database,
    *,
    executor: FakeQueryExecutor | None = None,
    redis: FakeRedisGateway | None = None,
    loki: FakeLokiClient | None = None,
) -> PlatformService:
    snapshot = PlatformTopologySnapshotBuilder(
        PlatformConfigRepository(database),
        resolver=MappingSecretResolver(_secret_values()),
    ).build_runtime_snapshot()
    return PlatformService(
        registry=TopologyRegistry(snapshot.topology),
        access_policy=snapshot.access_policy,
        executors={
            DatabaseEngine.MYSQL: executor or FakeQueryExecutor(),
            DatabaseEngine.SQLSERVER: FakeQueryExecutor(),
            DatabaseEngine.ORACLE: FakeQueryExecutor(),
        },
        schema_readers={DatabaseEngine.MYSQL: FakeSchemaDirectoryReader()},
        redis_gateway=redis or FakeRedisGateway(),
        loki_client=loki or FakeLokiClient(),
        config_source=snapshot.source,
        config_revision=snapshot.revision,
        config_hash=snapshot.config_hash,
        config_errors=snapshot.errors,
        config_resource_count=snapshot.resource_count,
    )


class PlatformConfigRepositoryTests(unittest.TestCase):
    def test_yaml_import_upserts_topology_and_runtime_snapshot(self) -> None:
        c = container()
        result = c.platform_config_service.import_topology_yaml(
            path=_example_yaml_path(),
            actor_id="local-user",
        )

        self.assertGreater(result["created"], 0)
        self.assertEqual([], result["errors"])
        self.assertEqual(2, c.agent_repository.count_rows("platform_environment"))
        self.assertGreater(c.agent_repository.count_rows("platform_resource_binding"), 0)

        public = c.platform_config_service.public_snapshot()
        self.assertEqual("database", public["source"])
        self.assertEqual(6, public["resource_count"])
        self.assertEqual(2, public["access_grant_count"])
        self.assertRegex(public["config_hash"], r"^[0-9a-f]{64}$")
        encoded = str(public)
        self.assertIn("secret://sanjiu/guanlan/db_password", encoded)
        self.assertNotIn("db-password", encoded)

        builder = PlatformTopologySnapshotBuilder(
            PlatformConfigRepository(c.database),
            resolver=MappingSecretResolver(_secret_values()),
        )
        runtime = builder.build_runtime_snapshot()
        self.assertEqual("database", runtime.source)
        self.assertEqual(6, runtime.resource_count)
        self.assertRegex(runtime.config_hash, r"^[0-9a-f]{64}$")
        self.assertEqual([], runtime.errors)
        guanlan = runtime.topology.environment("sanjiu").base("guanlan")  # type: ignore[union-attr]
        self.assertEqual("mysql.guanlan", guanlan.database.host)  # type: ignore[union-attr]
        self.assertIn("local-user", runtime.access_policy.scopes)

    def test_runtime_snapshot_empty_invalid_and_disabled_resource_paths(self) -> None:
        tmp, database, _ = _file_database()
        self.addCleanup(tmp.cleanup)
        repository = PlatformConfigRepository(database)

        empty = PlatformTopologySnapshotBuilder(repository).build_runtime_snapshot()
        self.assertEqual("database-empty", empty.source)
        self.assertEqual(0, empty.resource_count)
        self.assertRegex(empty.config_hash, r"^[0-9a-f]{64}$")

        repository.upsert_environment(code="prod")
        repository.upsert_base(environment_code="prod", code="main", engine="mysql")
        repository.upsert_resource_binding(
            code="prod_main_database",
            scope_type="base",
            environment_code="prod",
            base_code="main",
            resource_kind="database",
            engine="mysql",
            config={"port": 3306, "database": "erp", "user": "reader"},
        )

        invalid = PlatformTopologySnapshotBuilder(repository).build_runtime_snapshot()
        self.assertEqual("database-invalid", invalid.source)
        self.assertFalse(invalid.valid)
        self.assertIn("missing required field: host", str(invalid.errors))

        repository.set_resource_binding_status("prod_main_database", "disabled")
        disabled = PlatformTopologySnapshotBuilder(repository).build_runtime_snapshot()
        self.assertEqual("database", disabled.source)
        self.assertEqual(0, disabled.resource_count)
        self.assertIsNone(
            disabled.topology.environment("prod").base("main").database  # type: ignore[union-attr]
        )
        database.close()

    def test_rejects_raw_secret_in_resource_config(self) -> None:
        c = container()
        c.platform_config_service.upsert_environment(
            {"code": "prod"},
            actor_id="local-user",
        )
        c.platform_config_service.upsert_base(
            {"environment_code": "prod", "code": "main", "engine": "mysql"},
            actor_id="local-user",
        )

        with self.assertRaises(Exception) as raised:
            c.platform_config_service.upsert_resource_binding(
                {
                    "code": "prod_main_database",
                    "scope_type": "base",
                    "environment_code": "prod",
                    "base_code": "main",
                    "resource_kind": "database",
                    "engine": "mysql",
                    "config": {"host": "mysql", "password": "plain-secret"},
                },
                actor_id="local-user",
            )
        self.assertIn("Secret payload", str(raised.exception))

    def test_platform_config_repository_does_not_read_runtime_tables(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "modules"
            / "platform_config"
            / "infrastructure"
            / "repository.py"
        ).read_text()

        for runtime_table in (
            "agent_job",
            "agent_message",
            "agent_tool_call",
            "agent_step",
            "delivery_attempt",
        ):
            self.assertNotIn(runtime_table, source)


class PlatformConfigApiTests(unittest.TestCase):
    def test_platform_config_api_imports_yaml_and_exposes_snapshot(self) -> None:
        built = []
        settings = make_settings()

        def factory(_: Settings):
            c = container()
            built.append(c)
            return c

        with TestClient(create_app(settings, container_factory=factory)) as client:
            denied = client.post(
                "/api/platform/environments",
                json={"code": "prod"},
                headers={"x-admin-user-id": "unknown"},
            )
            self.assertEqual(403, denied.status_code)

            imported = client.post(
                "/api/platform/import/topology-yaml",
                json={"path": "config/internal_platform_topology.example.yaml"},
                headers={"x-admin-user-id": "local-user"},
            )
            self.assertEqual(200, imported.status_code)
            self.assertGreater(imported.json()["import"]["created"], 0)

            snapshot = client.get("/api/platform/topology-snapshot")
            self.assertEqual(200, snapshot.status_code)
            snapshot_body = snapshot.json()["snapshot"]
            self.assertEqual("database", snapshot_body["source"])
            self.assertEqual(6, snapshot_body["resource_count"])
            self.assertEqual(2, snapshot_body["access_grant_count"])
            self.assertRegex(snapshot_body["config_hash"], r"^[0-9a-f]{64}$")

            rejected = client.post(
                "/api/platform/resource-bindings",
                json={
                    "code": "bad_db",
                    "scope_type": "base",
                    "environment_code": "sanjiu",
                    "base_code": "guanlan",
                    "resource_kind": "database",
                    "engine": "mysql",
                    "config": {"host": "mysql", "password": "raw"},
                },
                headers={"x-admin-user-id": "local-user"},
            )
            self.assertEqual(400, rejected.status_code)
            self.assertIn("Secret payload", rejected.json()["detail"])

            self.assertGreater(
                built[0].agent_repository.count_rows("platform_config_audit"),
                0,
            )

    def test_platform_config_api_snapshot_hash_changes_when_resource_disabled(self) -> None:
        built = []
        settings = make_settings()

        def factory(_: Settings):
            c = container()
            built.append(c)
            return c

        with TestClient(create_app(settings, container_factory=factory)) as client:
            imported = client.post(
                "/api/platform/import/topology-yaml",
                json={"path": "config/internal_platform_topology.example.yaml"},
                headers={"x-admin-user-id": "local-user"},
            )
            self.assertEqual(200, imported.status_code)
            before = client.get("/api/platform/topology-snapshot").json()["snapshot"]
            disabled = client.post(
                "/api/platform/resource-bindings/sanjiu_guanlan_loki/disable",
                headers={"x-admin-user-id": "local-user"},
            )
            self.assertEqual(200, disabled.status_code)
            after = client.get("/api/platform/topology-snapshot").json()["snapshot"]

            self.assertNotEqual(before["config_hash"], after["config_hash"])
            self.assertEqual(before["resource_count"] - 1, after["resource_count"])
            self.assertNotIn("sanjiu_guanlan_loki", str(after))
            self.assertGreater(
                built[0].agent_repository.count_rows("platform_config_audit"),
                0,
            )


class InternalApiPlatformDbConfigTests(unittest.TestCase):
    def test_internal_api_platform_prefers_db_snapshot(self) -> None:
        tmp, dsn = _import_example_to_file_database()
        self.addCleanup(tmp.cleanup)
        with tempfile.TemporaryDirectory() as yaml_tmp:
            yaml_path = Path(yaml_tmp) / "fallback.yaml"
            yaml_path.write_text(
                """
                environments:
                  yaml_only:
                    bases:
                      main:
                        engine: mysql
                access:
                  yaml-user:
                    - { environment: "*", base: "*", workshop: "*" }
                """,
            )
            env_values = {
                "SECRET_SANJIU_GUANLAN_DB_HOST": "mysql.guanlan",
                "SECRET_SANJIU_GUANLAN_DB_USER": "reader",
                "SECRET_SANJIU_GUANLAN_DB_PASSWORD": "db-password",
                "SECRET_SANJIU_GUANLAN_REDIS_HOST": "redis.guanlan",
                "SECRET_SANJIU_GUANLAN_LOKI_URL": "http://loki.guanlan:3100",
                "SECRET_MMK_MAIN_DB_HOST": "mssql.mmk",
                "SECRET_MMK_MAIN_DB_USER": "reader",
                "SECRET_MMK_MAIN_DB_PASSWORD": "mmk-password",
                "SECRET_MMK_MAIN_REDIS_HOST": "redis.mmk",
                "SECRET_MMK_MAIN_LOKI_URL": "http://loki.mmk:3100",
                "INTERNAL_PLATFORM_TOPOLOGY_FILE": str(yaml_path),
            }
            with patch.dict(os.environ, env_values, clear=False):
                service = build_service(Settings(database_dsn=dsn, app_startup_migrate=True))

            self.assertEqual("database", service.config_status()["source"])
            self.assertTrue(service.config_status()["valid"])
            self.assertRegex(service.config_status()["config_hash"], r"^[0-9a-f]{64}$")
            directory = service.topology_directory(user_id="local-user")
            self.assertIn(
                "sanjiu",
                {environment["code"] for environment in directory["environments"]},
            )
            self.assertNotIn("yaml_only", str(directory))

    def test_internal_api_platform_empty_db_can_fallback_to_yaml(self) -> None:
        tmp, database, dsn = _file_database()
        self.addCleanup(tmp.cleanup)
        database.close()

        with patch.dict(
            os.environ,
            {"INTERNAL_PLATFORM_TOPOLOGY_FILE": str(_example_yaml_path())},
            clear=False,
        ):
            fallback = _load_topology_snapshot(Settings(database_dsn=dsn, app_startup_migrate=True))
        self.assertEqual("yaml", fallback.source)
        self.assertEqual(6, fallback.resource_count)

        with patch.dict(os.environ, {"INTERNAL_PLATFORM_TOPOLOGY_FILE": ""}, clear=False):
            empty = _load_topology_snapshot(Settings(database_dsn=dsn, app_startup_migrate=True))
        self.assertEqual("database-empty", empty.source)

    def test_invalid_db_snapshot_does_not_fallback_to_yaml_and_health_is_degraded(self) -> None:
        tmp, database, dsn = _file_database()
        self.addCleanup(tmp.cleanup)
        repository = PlatformConfigRepository(database)
        repository.upsert_environment(code="prod")
        repository.upsert_base(environment_code="prod", code="main", engine="mysql")
        repository.upsert_resource_binding(
            code="prod_main_database",
            scope_type="base",
            environment_code="prod",
            base_code="main",
            resource_kind="database",
            engine="mysql",
            config={"port": 3306, "database": "erp", "user": "reader"},
        )
        database.close()

        with patch.dict(
            os.environ,
            {"INTERNAL_PLATFORM_TOPOLOGY_FILE": str(_example_yaml_path())},
            clear=False,
        ):
            service = build_service(Settings(database_dsn=dsn, app_startup_migrate=True))

        status = service.config_status()
        self.assertEqual("database-invalid", status["source"])
        self.assertFalse(status["valid"])
        self.assertIn("missing required field: host", str(status["errors"]))

        with TestClient(create_internal_platform_app(service=service)) as client:
            health = client.get("/health")
        self.assertEqual(200, health.status_code)
        self.assertEqual("degraded", health.json()["status"])
        self.assertEqual("database-invalid", health.json()["config"]["source"])

    def test_db_backed_tools_preserve_policies_and_do_not_leak_secrets(self) -> None:
        c = container()
        c.platform_config_service.import_topology_yaml(
            path=_example_yaml_path(), actor_id="local-user"
        )
        service = _db_backed_service(
            c.database,
            executor=FakeQueryExecutor(rows=[{"order_no": "MO1", "status": "WAIT"}]),
            redis=FakeRedisGateway(values={"GL001:order:1": "WAIT"}),
            loki=FakeLokiClient(),
        )

        resolved = service.describe_target(
            user_id="local-user",
            environment="sanjiu",
            base="guanlan",
            workshop="GL001",
            kind=ResourceKind.DATABASE,
        )
        self.assertEqual("sanjiu", resolved.summary["environment"])
        self.assertEqual("guanlan", resolved.summary["base"])
        self.assertEqual("GL001", resolved.summary["workshop"])

        database_result = service.query_database(
            user_id="local-user",
            environment="sanjiu",
            base="guanlan",
            workshop="GL001",
            sql="select * from GL001_EBR_order",
            limit=10,
        )
        self.assertEqual(1, database_result.summary["row_count"])
        with self.assertRaises(PolicyViolation):
            service.query_database(
                user_id="local-user",
                environment="sanjiu",
                base="guanlan",
                workshop="GL001",
                sql="select * from GL002_EBR_order",
            )

        redis_result = service.redis_get(
            user_id="local-user",
            environment="sanjiu",
            base="guanlan",
            workshop="GL001",
            key="GL001:order:1",
        )
        self.assertEqual("WAIT", redis_result.summary["value_summary"])
        with self.assertRaises(PolicyViolation):
            service.redis_get(
                user_id="local-user",
                environment="sanjiu",
                base="guanlan",
                workshop="GL001",
                key="GL002:order:1",
            )

        loki = FakeLokiClient()
        service = _db_backed_service(c.database, loki=loki)
        service.query_loki(
            user_id="local-user",
            environment="sanjiu",
            base="guanlan",
            workshop="GL001",
            selector={"service": "order-service"},
            query="Material",
            minutes=5,
            limit=10,
        )
        self.assertEqual(
            {"service": "order-service", "workshop": "GL001"},
            loki.calls[0]["selector"],
        )

        health_text = str(service.config_status())
        self.assertNotIn("db-password", health_text)
        self.assertNotIn("redis.guanlan", health_text)

    def test_db_backed_access_grants_allow_deny_and_disabled_resource(self) -> None:
        c = container()
        c.platform_config_service.import_topology_yaml(
            path=_example_yaml_path(), actor_id="local-user"
        )
        repository = PlatformConfigRepository(c.database)
        repository.upsert_access_grant(
            subject_type="user",
            subject_code="limited-user",
            effect="allow",
            environment_code="sanjiu",
            base_code="guanlan",
            workshop_code="GL001",
            priority=100,
        )
        deny = repository.upsert_access_grant(
            subject_type="user",
            subject_code="limited-user",
            effect="deny",
            environment_code="sanjiu",
            base_code="guanlan",
            workshop_code="GL001",
            priority=1,
        )
        service = _db_backed_service(c.database)
        with self.assertRaises(AuthorizationError):
            service.describe_target(
                user_id="limited-user",
                environment="sanjiu",
                base="guanlan",
                workshop="GL001",
                kind=ResourceKind.DATABASE,
            )

        repository.set_access_grant_status(deny["id"], "disabled")
        service = _db_backed_service(c.database)
        allowed = service.describe_target(
            user_id="limited-user",
            environment="sanjiu",
            base="guanlan",
            workshop="GL001",
            kind=ResourceKind.DATABASE,
        )
        self.assertEqual("sanjiu", allowed.summary["environment"])
        self.assertEqual("guanlan", allowed.summary["base"])
        self.assertEqual("GL001", allowed.summary["workshop"])

        repository.set_resource_binding_status("sanjiu_guanlan_database", "disabled")
        disabled_snapshot = PlatformTopologySnapshotBuilder(repository).build_runtime_snapshot()
        self.assertEqual(5, disabled_snapshot.resource_count)
        self.assertIsNone(
            disabled_snapshot.topology.environment("sanjiu").base("guanlan").database  # type: ignore[union-attr]
        )


if __name__ == "__main__":
    unittest.main()
