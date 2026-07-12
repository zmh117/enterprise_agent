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
    SchemaInspectorFactory,
)
from app.modules.internal_api_platform.infrastructure.loki_gateway import FakeLokiClient
from app.modules.internal_api_platform.infrastructure.redis_gateway import FakeRedisGateway
from app.modules.internal_api_platform.infrastructure.registry import TopologyRegistry
from app.modules.internal_api_platform.infrastructure.secrets import MappingSecretResolver
from app.modules.internal_api_platform.infrastructure.secrets import DbBackedSecretResolver
from app.modules.platform_config.application.snapshot import PlatformTopologySnapshotBuilder
from app.modules.platform_config.infrastructure import PlatformConfigRepository
from app.shared.config import Settings
from app.shared.database import Database, default_migrations_dir
from app.shared.runtime_config_loader import apply_runtime_config_overlay
from backend.tests.helpers import container, test_settings as make_settings


def _example_yaml_path() -> Path:
    return (
        Path(__file__).resolve().parents[1] / "config" / "internal_platform_topology.example.yaml"
    )


def _secret_values() -> dict[str, str]:
    return {
        "secret://sanjiu/guanlan_cloud/db_host": "10.0.102.240",
        "secret://sanjiu/guanlan_cloud/db_user": "system",
        "secret://sanjiu/guanlan_cloud/db_password": "db-password",
        "secret://sanjiu/guanlan_edge/db_host": "10.0.102.106",
        "secret://sanjiu/guanlan_edge/db_user": "system",
        "secret://sanjiu/guanlan_edge/db_password": "db-password",
        "secret://sanjiu/guanlan_edge/redis_password": "redis-password",
        "secret://sanjiu/shunfeng_cloud/db_host": "10.0.102.240",
        "secret://sanjiu/shunfeng_cloud/db_user": "system",
        "secret://sanjiu/shunfeng_cloud/db_password": "db-password",
        "secret://sanjiu/shunfeng_edge/db_host": "10.0.102.116",
        "secret://sanjiu/shunfeng_edge/db_user": "system",
        "secret://sanjiu/shunfeng_edge/db_password": "db-password",
        "secret://sanjiu/shunfeng_edge/redis_password": "redis-password",
        "secret://sanjiu/chenzhou_cloud/db_host": "10.0.102.240",
        "secret://sanjiu/chenzhou_cloud/db_user": "system",
        "secret://sanjiu/chenzhou_cloud/db_password": "db-password",
        "secret://sanjiu/chenzhou_edge/db_host": "10.0.102.88",
        "secret://sanjiu/chenzhou_edge/db_user": "system",
        "secret://sanjiu/chenzhou_edge/db_password": "db-password",
        "secret://sanjiu/chenzhou_edge/redis_password": "redis-password",
        "secret://sanjiu/cloud/redis_password": "redis-password",
        "secret://xt/mes51/db_host": "10.0.125.102",
        "secret://xt/mes51/db_user": "root",
        "secret://xt/mes51/db_password": "db-password",
        "secret://mmk/main/db_host": "10.0.102.130",
        "secret://mmk/main/db_user": "sa",
        "secret://mmk/main/db_password": "mmk-password",
        "secret://agent_test/mysql/db_host": "agent-test-mysql",
        "secret://agent_test/mysql/db_user": "agent_test_reader",
        "secret://agent_test/mysql/db_password": "mysql-reader-password",
        "secret://agent_test/mysql/redis_host": "agent-test-redis-mysql",
        "secret://agent_test/mysql/redis_user": "agent_test_reader",
        "secret://agent_test/mysql/redis_password": "mysql-redis-reader-password",
        "secret://agent_test/sqlserver/db_host": "agent-test-sqlserver",
        "secret://agent_test/sqlserver/db_user": "agent_test_reader",
        "secret://agent_test/sqlserver/db_password": "sqlserver-reader-password",
        "secret://agent_test/sqlserver/redis_host": "agent-test-redis-sqlserver",
        "secret://agent_test/sqlserver/redis_user": "agent_test_reader",
        "secret://agent_test/sqlserver/redis_password": "sqlserver-redis-reader-password",
        "secret://agent_test/loki/base_url": "http://loki:3100",
    }


# 6 Oracle bases × (db+redis) + xt db + mmk db + agent_test × (2 db + 2 redis + 2 loki)
_EXAMPLE_RESOURCE_COUNT = 20


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
        schema_inspector_factory=SchemaInspectorFactory(
            {
                DatabaseEngine.MYSQL: FakeSchemaDirectoryReader(),
                DatabaseEngine.SQLSERVER: FakeSchemaDirectoryReader(),
                DatabaseEngine.ORACLE: FakeSchemaDirectoryReader(),
            }
        ),
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
        self.assertEqual(4, c.agent_repository.count_rows("platform_environment"))
        self.assertGreater(c.agent_repository.count_rows("platform_resource_binding"), 0)

        public = c.platform_config_service.public_snapshot()
        self.assertEqual("database", public["source"])
        self.assertEqual(_EXAMPLE_RESOURCE_COUNT, public["resource_count"])
        self.assertEqual(3, public["access_grant_count"])
        self.assertRegex(public["config_hash"], r"^[0-9a-f]{64}$")
        encoded = str(public)
        self.assertIn("secret://sanjiu/guanlan_cloud/db_password", encoded)
        self.assertNotIn("db-password", encoded)

        builder = PlatformTopologySnapshotBuilder(
            PlatformConfigRepository(c.database),
            resolver=MappingSecretResolver(_secret_values()),
        )
        runtime = builder.build_runtime_snapshot()
        self.assertEqual("database", runtime.source)
        self.assertEqual(_EXAMPLE_RESOURCE_COUNT, runtime.resource_count)
        self.assertRegex(runtime.config_hash, r"^[0-9a-f]{64}$")
        self.assertEqual([], runtime.errors)
        guanlan = runtime.topology.environment("sanjiu").base("guanlan_cloud")  # type: ignore[union-attr]
        self.assertEqual("10.0.102.240", guanlan.database.host)  # type: ignore[union-attr]
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
            self.assertEqual(_EXAMPLE_RESOURCE_COUNT, snapshot_body["resource_count"])
            self.assertEqual(3, snapshot_body["access_grant_count"])
            self.assertRegex(snapshot_body["config_hash"], r"^[0-9a-f]{64}$")

            rejected = client.post(
                "/api/platform/resource-bindings",
                json={
                    "code": "bad_db",
                    "scope_type": "base",
                    "environment_code": "sanjiu",
                    "base_code": "guanlan_cloud",
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

    def test_platform_secrets_api_is_write_only_and_rotatable(self) -> None:
        settings = make_settings()

        with patch.dict(os.environ, {"APP_CONFIG_MASTER_KEY": "test-master-key"}, clear=False):
            with TestClient(create_app(settings, container_factory=lambda _: container())) as client:
                denied = client.post(
                    "/api/platform/secrets",
                    json={"code": "deepseek_api_key", "value": "sk-secret-1234"},
                    headers={"x-admin-user-id": "unknown"},
                )
                self.assertEqual(403, denied.status_code)

                created = client.post(
                    "/api/platform/secrets",
                    json={
                        "code": "deepseek_api_key",
                        "value": "sk-secret-1234",
                        "purpose": "claude-runtime",
                    },
                    headers={"x-admin-user-id": "local-user"},
                )
                self.assertEqual(200, created.status_code)
                body = created.json()["secret"]
                self.assertEqual("secret://platform/deepseek_api_key", body["secret_ref"])
                self.assertNotIn("sk-secret-1234", str(created.json()))

                rotated = client.post(
                    "/api/platform/secrets/deepseek_api_key/rotate",
                    json={"value": "sk-secret-5678"},
                    headers={"x-admin-user-id": "local-user"},
                )
                self.assertEqual(200, rotated.status_code)
                self.assertEqual(2, rotated.json()["secret"]["active_version"])
                self.assertNotIn("sk-secret-5678", str(rotated.json()))

                disabled = client.post(
                    "/api/platform/secrets/deepseek_api_key/disable",
                    headers={"x-admin-user-id": "local-user"},
                )
                self.assertEqual(200, disabled.status_code)
                self.assertFalse(disabled.json()["secret"]["configured"])

    def test_runtime_config_api_snapshot_and_bootstrap_guard(self) -> None:
        settings = make_settings()

        with patch.dict(os.environ, {"APP_CONFIG_MASTER_KEY": "test-master-key"}, clear=False):
            with TestClient(create_app(settings, container_factory=lambda _: container())) as client:
                definitions = client.get("/api/platform/runtime-config/definitions")
                self.assertEqual(200, definitions.status_code)
                keys = {item["key"] for item in definitions.json()["definitions"]}
                self.assertIn("ANTHROPIC_MODEL", keys)

                rejected = client.post(
                    "/api/platform/runtime-config/values",
                    json={"key": "DATABASE_DSN", "value": "sqlite:///bad.db"},
                    headers={"x-admin-user-id": "local-user"},
                )
                self.assertEqual(400, rejected.status_code)
                self.assertIn("bootstrap-only", rejected.json()["detail"])

                global_value = client.post(
                    "/api/platform/runtime-config/values",
                    json={"key": "AGENT_MAX_TURNS", "value": 8},
                    headers={"x-admin-user-id": "local-user"},
                )
                self.assertEqual(200, global_value.status_code)
                service_value = client.post(
                    "/api/platform/runtime-config/values",
                    json={
                        "key": "AGENT_MAX_TURNS",
                        "scope_type": "service",
                        "scope_code": "agent-worker",
                        "service_name": "agent-worker",
                        "value": 12,
                    },
                    headers={"x-admin-user-id": "local-user"},
                )
                self.assertEqual(200, service_value.status_code)

                snapshot = client.get(
                    "/api/platform/runtime-config/snapshot",
                    params={"service_name": "agent-worker"},
                )
                self.assertEqual(200, snapshot.status_code)
                effective = snapshot.json()["snapshot"]["effective_masked"]
                self.assertEqual(12, effective["AGENT_MAX_TURNS"]["value"])

                secret = client.post(
                    "/api/platform/secrets",
                    json={"code": "deepseek_api_key", "value": "sk-real-secret"},
                    headers={"x-admin-user-id": "local-user"},
                )
                self.assertEqual(200, secret.status_code)
                key_value = client.post(
                    "/api/platform/runtime-config/values",
                    json={
                        "key": "ANTHROPIC_API_KEY",
                        "secret_ref": "secret://platform/deepseek_api_key",
                    },
                    headers={"x-admin-user-id": "local-user"},
                )
                self.assertEqual(200, key_value.status_code)
                self.assertNotIn("sk-real-secret", str(key_value.json()))

    def test_platform_config_api_reports_missing_topology_yaml_path(self) -> None:
        settings = make_settings()

        with TestClient(create_app(settings, container_factory=lambda _: container())) as client:
            missing = client.post(
                "/api/platform/import/topology-yaml",
                json={"path": "config/missing_topology.yaml"},
                headers={"x-admin-user-id": "local-user"},
            )

        self.assertEqual(404, missing.status_code)
        self.assertEqual("Topology YAML file not found", missing.json()["detail"])

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
                "/api/platform/resource-bindings/sanjiu_guanlan_cloud_redis/disable",
                headers={"x-admin-user-id": "local-user"},
            )
            self.assertEqual(200, disabled.status_code)
            after = client.get("/api/platform/topology-snapshot").json()["snapshot"]

            self.assertNotEqual(before["config_hash"], after["config_hash"])
            self.assertEqual(before["resource_count"] - 1, after["resource_count"])
            self.assertNotIn("sanjiu_guanlan_cloud_redis", str(after))
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
                **{
                    f"SECRET_{ref.removeprefix('secret://').upper().replace('/', '_').replace('-', '_')}": value
                    for ref, value in _secret_values().items()
                },
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
        self.assertEqual(_EXAMPLE_RESOURCE_COUNT, fallback.resource_count)

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
            base="guanlan_cloud",
            workshop="GL001",
            kind=ResourceKind.DATABASE,
        )
        self.assertEqual("sanjiu", resolved.summary["environment"])
        self.assertEqual("guanlan_cloud", resolved.summary["base"])
        self.assertEqual("GL001", resolved.summary["workshop"])

        database_result = service.query_database(
            user_id="local-user",
            environment="sanjiu",
            base="guanlan_cloud",
            workshop="GL001",
            sql="select * from GL001_EBR_order",
            limit=10,
        )
        self.assertEqual(1, database_result.summary["row_count"])
        with self.assertRaises(PolicyViolation):
            service.query_database(
                user_id="local-user",
                environment="sanjiu",
                base="guanlan_cloud",
                workshop="GL001",
                sql="select * from GL002_EBR_order",
            )

        redis_result = service.redis_get(
            user_id="local-user",
            environment="sanjiu",
            base="guanlan_cloud",
            workshop="GL001",
            key="GL001:order:1",
        )
        self.assertEqual("WAIT", redis_result.summary["value_summary"])
        with self.assertRaises(PolicyViolation):
            service.redis_get(
                user_id="local-user",
                environment="sanjiu",
                base="guanlan_cloud",
                workshop="GL001",
                key="GL002:order:1",
            )

        health_text = str(service.config_status())
        self.assertNotIn("db-password", health_text)
        self.assertNotIn("10.0.102.240", health_text)

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
            base_code="guanlan_cloud",
            workshop_code="GL001",
            priority=100,
        )
        deny = repository.upsert_access_grant(
            subject_type="user",
            subject_code="limited-user",
            effect="deny",
            environment_code="sanjiu",
            base_code="guanlan_cloud",
            workshop_code="GL001",
            priority=1,
        )
        service = _db_backed_service(c.database)
        with self.assertRaises(AuthorizationError):
            service.describe_target(
                user_id="limited-user",
                environment="sanjiu",
                base="guanlan_cloud",
                workshop="GL001",
                kind=ResourceKind.DATABASE,
            )

        repository.set_access_grant_status(deny["id"], "disabled")
        service = _db_backed_service(c.database)
        allowed = service.describe_target(
            user_id="limited-user",
            environment="sanjiu",
            base="guanlan_cloud",
            workshop="GL001",
            kind=ResourceKind.DATABASE,
        )
        self.assertEqual("sanjiu", allowed.summary["environment"])
        self.assertEqual("guanlan_cloud", allowed.summary["base"])
        self.assertEqual("GL001", allowed.summary["workshop"])

        repository.set_resource_binding_status("sanjiu_guanlan_cloud_database", "disabled")
        disabled_snapshot = PlatformTopologySnapshotBuilder(repository).build_runtime_snapshot()
        self.assertEqual(_EXAMPLE_RESOURCE_COUNT - 1, disabled_snapshot.resource_count)
        self.assertIsNone(
            disabled_snapshot.topology.environment("sanjiu").base("guanlan_cloud").database  # type: ignore[union-attr]
        )


class PlatformSecretAndRuntimeConfigTests(unittest.TestCase):
    def test_encrypted_db_secret_provider_does_not_persist_plaintext(self) -> None:
        c = container()
        repository = PlatformConfigRepository(c.database)

        with patch.dict(os.environ, {"APP_CONFIG_MASTER_KEY": "test-master-key"}, clear=False):
            secret = c.platform_config_service.create_platform_secret(
                {
                    "code": "deepseek_api_key",
                    "value": "sk-sensitive-value",
                    "purpose": "claude-runtime",
                },
                actor_id="local-user",
            )
            self.assertEqual("secret://platform/deepseek_api_key", secret["secret_ref"])
            stored_versions = c.database.execute("select * from platform_secret_version")
            self.assertEqual(1, len(stored_versions))
            encoded = str(stored_versions)
            self.assertNotIn("sk-sensitive-value", encoded)

            resolver = DbBackedSecretResolver(repository, master_key="test-master-key")
            self.assertEqual(
                "sk-sensitive-value",
                resolver.resolve("secret://platform/deepseek_api_key"),
            )

            rotated = c.platform_config_service.rotate_platform_secret(
                "deepseek_api_key",
                {"value": "sk-rotated-value"},
                actor_id="local-user",
            )
            self.assertEqual(2, rotated["active_version"])
            self.assertEqual(
                "sk-rotated-value",
                resolver.resolve("secret://platform/deepseek_api_key"),
            )

            c.platform_config_service.disable_platform_secret(
                "deepseek_api_key",
                actor_id="local-user",
            )
            with self.assertRaises(Exception):
                resolver.resolve("secret://platform/deepseek_api_key")

        audit_text = str(repository.list_config_audit(limit=20))
        self.assertNotIn("sk-sensitive-value", audit_text)
        self.assertNotIn("sk-rotated-value", audit_text)

    def test_runtime_config_overlay_resolves_secret_backed_claude_settings(self) -> None:
        c = container()
        base = make_settings()

        with patch.dict(os.environ, {"APP_CONFIG_MASTER_KEY": "test-master-key"}, clear=False):
            c.platform_config_service.create_platform_secret(
                {"code": "deepseek_api_key", "value": "sk-db-configured"},
                actor_id="local-user",
            )
            c.platform_config_service.upsert_runtime_config_value(
                {
                    "key": "ANTHROPIC_BASE_URL",
                    "value": "https://api.deepseek.com/anthropic",
                    "service_name": "agent-worker",
                },
                actor_id="local-user",
            )
            c.platform_config_service.upsert_runtime_config_value(
                {
                    "key": "ANTHROPIC_MODEL",
                    "value": "deepseek-v4-pro[1m]",
                    "service_name": "agent-worker",
                },
                actor_id="local-user",
            )
            c.platform_config_service.upsert_runtime_config_value(
                {
                    "key": "ANTHROPIC_API_KEY",
                    "secret_ref": "secret://platform/deepseek_api_key",
                    "service_name": "agent-worker",
                },
                actor_id="local-user",
            )
            c.platform_config_service.upsert_runtime_config_value(
                {
                    "key": "FEATURE_REAL_CLAUDE",
                    "value": True,
                    "service_name": "agent-worker",
                },
                actor_id="local-user",
            )

            overlaid = apply_runtime_config_overlay(
                base,
                c.database,
                service_name="agent-worker",
            )

        self.assertEqual("https://api.deepseek.com/anthropic", overlaid.anthropic_base_url)
        self.assertEqual("deepseek-v4-pro[1m]", overlaid.claude_model)
        self.assertEqual("sk-db-configured", overlaid.anthropic_api_key)
        self.assertTrue(overlaid.feature_real_claude)
        self.assertEqual("database", overlaid.runtime_config_source)
        self.assertFalse(overlaid.runtime_config_degraded)

    def test_runtime_config_overlay_covers_internal_platform_and_dingtalk(self) -> None:
        c = container()
        base = make_settings()

        with patch.dict(os.environ, {"APP_CONFIG_MASTER_KEY": "test-master-key"}, clear=False):
            c.platform_config_service.create_platform_secret(
                {"code": "dingtalk_client_secret", "value": "dingtalk-secret"},
                actor_id="local-user",
            )
            c.platform_config_service.upsert_runtime_config_value(
                {"key": "INTERNAL_PLATFORM_MAX_ROWS", "value": 25},
                actor_id="local-user",
            )
            c.platform_config_service.upsert_runtime_config_value(
                {
                    "key": "DINGTALK_CLIENT_SECRET",
                    "secret_ref": "secret://platform/dingtalk_client_secret",
                    "service_name": "dingtalk-stream-ingress",
                },
                actor_id="local-user",
            )
            c.platform_config_service.upsert_runtime_config_value(
                {
                    "key": "DINGTALK_DEFAULT_ENVIRONMENT",
                    "value": "sanjiu",
                    "service_name": "dingtalk-stream-ingress",
                },
                actor_id="local-user",
            )

            platform_settings = apply_runtime_config_overlay(
                base,
                c.database,
                service_name="internal-api-platform",
            )
            dingtalk_settings = apply_runtime_config_overlay(
                base,
                c.database,
                service_name="dingtalk-stream-ingress",
            )

        self.assertEqual(25, platform_settings.internal_platform_max_rows)
        self.assertEqual("dingtalk-secret", dingtalk_settings.dingtalk.stream_client_secret)
        self.assertEqual("sanjiu", dingtalk_settings.dingtalk.default_environment)
        self.assertFalse(dingtalk_settings.runtime_config_degraded)

        with patch.dict(os.environ, {"APP_CONFIG_MASTER_KEY": "test-master-key"}, clear=False):
            c.platform_config_service.upsert_runtime_config_value(
                {
                    "key": "DINGTALK_CLIENT_SECRET",
                    "secret_ref": "secret://platform/missing_secret",
                    "service_name": "dingtalk-stream-ingress",
                },
                actor_id="local-user",
            )
            degraded = apply_runtime_config_overlay(
                base,
                c.database,
                service_name="dingtalk-stream-ingress",
            )
        self.assertTrue(degraded.runtime_config_degraded)
        self.assertIn("Platform secret is disabled or missing", str(degraded.runtime_config_errors))


if __name__ == "__main__":
    unittest.main()
