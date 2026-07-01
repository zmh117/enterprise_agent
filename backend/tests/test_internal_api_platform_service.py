from __future__ import annotations

import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.modules.internal_api_platform.app import create_app
from app.modules.internal_api_platform.application.platform_service import PlatformService
from app.modules.internal_api_platform.domain.topology import DatabaseEngine
from app.modules.internal_api_platform.infrastructure.config import load_platform_config
from app.modules.internal_api_platform.infrastructure.db.executor import FakeQueryExecutor
from app.modules.internal_api_platform.infrastructure.loki_gateway import FakeLokiClient
from app.modules.internal_api_platform.infrastructure.redis_gateway import FakeRedisGateway
from app.modules.internal_api_platform.infrastructure.registry import TopologyRegistry
from app.modules.internal_api_platform.infrastructure.secrets import MappingSecretResolver

_CONFIG = textwrap.dedent(
    """
    environments:
      sanjiu:
        bases:
          guanlan:
            engine: mysql
            database:
              host_ref: secret://sanjiu/guanlan/db_host
              port: 3306
              database: erp
              user: reader
              password_ref: secret://sanjiu/guanlan/db_password
            redis:
              host: redis.guanlan
              port: 6379
            loki:
              base_url: http://loki.guanlan:3100
              tenant: sanjiu-guanlan
            workshops:
              GL001:
                table_prefix: GL001_EBR_
                redis_key_prefix: "GL001:"
                loki_label: { workshop: GL001 }
              GL002:
                table_prefix: GL002_EBR_
                redis_key_prefix: "GL002:"
                loki_label: { workshop: GL002 }
      mmk:
        bases:
          main:
            engine: sqlserver
            database:
              host: mssql.mmk
              port: 1433
              database: mes
              user: reader
              password: pw
            redis:
              host: redis.mmk
              port: 6379
            loki:
              base_url: http://loki.mmk:3100
    access:
      alice:
        - { environment: sanjiu, base: guanlan, workshop: GL001 }
      operator:
        - { environment: "*", base: "*", workshop: "*" }
    """
)


def _load() -> tuple[TopologyRegistry, object]:
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "topology.yaml"
        path.write_text(_CONFIG)
        topology, access = load_platform_config(
            path,
            resolver=MappingSecretResolver(
                {
                    "secret://sanjiu/guanlan/db_host": "mysql.guanlan",
                    "secret://sanjiu/guanlan/db_password": "s3cret",
                }
            ),
        )
    return TopologyRegistry(topology), access


def _service(
    *,
    executor: FakeQueryExecutor | None = None,
    redis: FakeRedisGateway | None = None,
    loki: FakeLokiClient | None = None,
) -> PlatformService:
    registry, access = _load()
    return PlatformService(
        registry=registry,
        access_policy=access,  # type: ignore[arg-type]
        executors={
            DatabaseEngine.MYSQL: executor or FakeQueryExecutor(),
            DatabaseEngine.SQLSERVER: FakeQueryExecutor(),
        },
        redis_gateway=redis or FakeRedisGateway(),
        loki_client=loki or FakeLokiClient(),
        max_rows=100,
        redis_scan_limit=200,
    )


class ConfigTests(unittest.TestCase):
    def test_resolves_secret_refs_and_topology(self) -> None:
        registry, _ = _load()
        base = registry.topology.environment("sanjiu").base("guanlan")  # type: ignore[union-attr]
        self.assertEqual(DatabaseEngine.MYSQL, base.engine)
        self.assertEqual("mysql.guanlan", base.database.host)  # type: ignore[union-attr]
        self.assertEqual("s3cret", base.database.password)  # type: ignore[union-attr]
        self.assertTrue(base.is_partitioned)
        mmk = registry.topology.environment("mmk").base("main")  # type: ignore[union-attr]
        self.assertFalse(mmk.is_partitioned)


class ExampleConfigTests(unittest.TestCase):
    def test_shipped_example_topology_is_valid(self) -> None:
        path = (
            Path(__file__).resolve().parents[1]
            / "config"
            / "internal_platform_topology.example.yaml"
        )
        topology, access = load_platform_config(path, resolver=MappingSecretResolver({}))
        self.assertIn("sanjiu", topology.environments)
        self.assertIn("mmk", topology.environments)
        guanlan = topology.environment("sanjiu").base("guanlan")  # type: ignore[union-attr]
        self.assertTrue(guanlan.is_partitioned)
        self.assertEqual({"GL001", "GL002"}, set(guanlan.workshops))
        self.assertFalse(topology.environment("mmk").base("main").is_partitioned)  # type: ignore[union-attr]
        self.assertIn("local-user", access.scopes)


class LokiClientTests(unittest.TestCase):
    def test_transient_upstream_error_is_retryable(self) -> None:
        import io
        import urllib.error

        from app.modules.internal_api_platform.domain.addressing import ResourceBinding
        from app.modules.internal_api_platform.domain.errors import UpstreamUnavailable
        from app.modules.internal_api_platform.domain.topology import (
            Base,
            DatabaseEngine,
            Environment,
            LokiConnection,
            ResourceKind,
        )
        from app.modules.internal_api_platform.infrastructure.loki_gateway import HttpLokiClient

        def failing(request: object, timeout: int) -> object:
            raise urllib.error.HTTPError(
                url="http://loki",
                code=503,
                msg="busy",
                hdrs={},  # type: ignore[arg-type]
                fp=io.BytesIO(b"{}"),
            )

        base = Base(
            code="main", engine=DatabaseEngine.MYSQL, loki=LokiConnection("http://loki:3100")
        )
        binding = ResourceBinding(
            environment=Environment(code="mmk", bases={"main": base}),
            base=base,
            kind=ResourceKind.LOKI,
            workshop=None,
            engine=DatabaseEngine.MYSQL,
            loki=base.loki,
        )
        client = HttpLokiClient(
            max_minutes=60, max_lines=500, max_response_chars=4000, urlopen_func=failing
        )
        with self.assertRaises(UpstreamUnavailable):
            client.query(binding, selector={"service": "s"}, query="", minutes=5, limit=10)


class ServiceTests(unittest.TestCase):
    def test_database_query_enforces_prefix_and_binds(self) -> None:
        executor = FakeQueryExecutor(rows=[{"order_no": "MO1", "status": "WAIT"}])
        service = _service(executor=executor)
        result = service.query_database(
            user_id="alice",
            environment="sanjiu",
            base="guanlan",
            workshop="GL001",
            sql="select * from GL001_EBR_order",
        )
        self.assertEqual(1, result.summary["row_count"])
        self.assertEqual([("mysql", "SELECT * FROM GL001_EBR_order LIMIT 100")], executor.calls)

    def test_database_query_denies_unauthorized_user(self) -> None:
        from app.modules.internal_api_platform.domain.errors import AuthorizationError

        service = _service()
        with self.assertRaises(AuthorizationError):
            service.query_database(
                user_id="alice",
                environment="sanjiu",
                base="guanlan",
                workshop="GL002",
                sql="select * from GL002_EBR_order",
            )

    def test_partitioned_base_requires_workshop(self) -> None:
        from app.modules.internal_api_platform.domain.errors import PolicyViolation

        service = _service()
        with self.assertRaises(PolicyViolation):
            service.query_database(
                user_id="operator",
                environment="sanjiu",
                base="guanlan",
                workshop=None,
                sql="select * from GL001_EBR_order",
            )

    def test_redis_get_enforces_namespace(self) -> None:
        from app.modules.internal_api_platform.domain.errors import PolicyViolation

        service = _service(redis=FakeRedisGateway(values={"GL001:order:1": "WAIT"}))
        result = service.redis_get(
            user_id="operator",
            environment="sanjiu",
            base="guanlan",
            workshop="GL001",
            key="GL001:order:1",
        )
        self.assertEqual("WAIT", result.summary["value_summary"])
        with self.assertRaises(PolicyViolation):
            service.redis_get(
                user_id="operator",
                environment="sanjiu",
                base="guanlan",
                workshop="GL001",
                key="GL002:order:1",
            )

    def test_loki_injects_workshop_label(self) -> None:
        loki = FakeLokiClient()
        service = _service(loki=loki)
        service.query_loki(
            user_id="operator",
            environment="sanjiu",
            base="guanlan",
            workshop="GL001",
            selector={"service": "order-service"},
            query="Material",
            minutes=5,
            limit=10,
        )
        self.assertEqual(
            {"service": "order-service", "workshop": "GL001"}, loki.calls[0]["selector"]
        )


class TopologyDirectoryTests(unittest.TestCase):
    def test_directory_is_filtered_by_access_and_hides_secrets(self) -> None:
        service = _service()
        alice = service.topology_directory(user_id="alice")
        # alice only has sanjiu/guanlan/GL001
        env = alice["environments"][0]
        self.assertEqual("sanjiu", env["code"])
        base = env["bases"][0]
        self.assertEqual("guanlan", base["code"])
        self.assertEqual([{"code": "GL001", "display_name": "", "aliases": []}], base["workshops"])
        self.assertNotIn("database", base)  # no connection details leaked
        self.assertNotIn("host", str(alice))

    def test_operator_sees_all_including_degenerate_base(self) -> None:
        service = _service()
        operator = service.topology_directory(user_id="operator")
        codes = {env["code"] for env in operator["environments"]}
        self.assertEqual({"sanjiu", "mmk"}, codes)
        mmk = next(e for e in operator["environments"] if e["code"] == "mmk")
        self.assertFalse(mmk["bases"][0]["partitioned"])
        self.assertEqual([], mmk["bases"][0]["workshops"])

    def test_er_context_embeds_addressing_directory(self) -> None:
        service = _service()
        response = service.er_context(user_id="alice", query="订单卡在等料")
        self.assertIn("addressing", response.summary)
        self.assertEqual(
            "guanlan",
            response.summary["addressing"]["environments"][0]["bases"][0]["code"],
        )

    def test_unknown_user_gets_empty_directory(self) -> None:
        service = _service()
        self.assertEqual({"environments": []}, service.topology_directory(user_id="ghost"))


class RouteTests(unittest.TestCase):
    def _client(self) -> TestClient:
        return TestClient(create_app(service=_service()))

    def test_database_route_requires_identity(self) -> None:
        response = self._client().post(
            "/tools/database/query",
            json={
                "environment": "sanjiu",
                "base": "guanlan",
                "workshop": "GL001",
                "sql": "select * from GL001_EBR_order",
            },
        )
        self.assertEqual(403, response.status_code)
        self.assertEqual("access_denied", response.json()["detail"]["error"]["code"])

    def test_database_route_happy_path(self) -> None:
        response = self._client().post(
            "/tools/database/query",
            json={
                "environment": "sanjiu",
                "base": "guanlan",
                "workshop": "GL001",
                "sql": "select * from GL001_EBR_order",
            },
            headers={"x-agent-user-id": "alice"},
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual("mysql", response.json()["summary"]["engine"])

    def test_er_context_route_returns_addressing(self) -> None:
        response = self._client().post(
            "/tools/context/er",
            json={"query": "order"},
            headers={"x-agent-user-id": "operator"},
        )
        self.assertEqual(200, response.status_code)
        codes = {env["code"] for env in response.json()["summary"]["addressing"]["environments"]}
        self.assertEqual({"sanjiu", "mmk"}, codes)

    def test_unknown_base_returns_404(self) -> None:
        response = self._client().post(
            "/tools/database/query",
            json={
                "environment": "sanjiu",
                "base": "nope",
                "workshop": "GL001",
                "sql": "select * from GL001_EBR_order",
            },
            headers={"x-agent-user-id": "operator"},
        )
        self.assertEqual(404, response.status_code)
        self.assertEqual("target_not_resolvable", response.json()["detail"]["error"]["code"])


if __name__ == "__main__":
    unittest.main()
