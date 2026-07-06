from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.internal_api_platform.app import build_service
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
        encoded = str(public)
        self.assertIn("secret://sanjiu/guanlan/db_password", encoded)
        self.assertNotIn("db-password", encoded)

        builder = PlatformTopologySnapshotBuilder(
            PlatformConfigRepository(c.database),
            resolver=MappingSecretResolver(_secret_values()),
        )
        runtime = builder.build_runtime_snapshot()
        self.assertEqual("database", runtime.source)
        self.assertEqual([], runtime.errors)
        guanlan = runtime.topology.environment("sanjiu").base("guanlan")  # type: ignore[union-attr]
        self.assertEqual("mysql.guanlan", guanlan.database.host)  # type: ignore[union-attr]
        self.assertIn("local-user", runtime.access_policy.scopes)

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
            self.assertEqual("database", snapshot.json()["snapshot"]["source"])

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


class InternalApiPlatformDbConfigTests(unittest.TestCase):
    def test_internal_api_platform_prefers_db_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "platform.db"
            dsn = f"sqlite:///{db_path}"
            database = Database(dsn)
            database.run_migrations(default_migrations_dir())
            repository = PlatformConfigRepository(database)
            from app.modules.platform_config.application.importer import (
                PlatformTopologyYamlImporter,
            )

            PlatformTopologyYamlImporter(repository).import_file(
                _example_yaml_path(),
                actor_id="local-user",
            )
            database.close()

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
            }
            with patch.dict(os.environ, env_values, clear=False):
                service = build_service(Settings(database_dsn=dsn, app_startup_migrate=True))

            self.assertEqual("database", service.config_status()["source"])
            self.assertTrue(service.config_status()["valid"])
            directory = service.topology_directory(user_id="local-user")
            self.assertIn(
                "sanjiu",
                {environment["code"] for environment in directory["environments"]},
            )


if __name__ == "__main__":
    unittest.main()
