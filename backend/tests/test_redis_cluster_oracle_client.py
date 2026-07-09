from __future__ import annotations

import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from app.modules.internal_api_platform.domain.addressing import ResourceBinding
from app.modules.internal_api_platform.domain.errors import PolicyViolation, ResolutionError
from app.modules.internal_api_platform.domain.redis_policy import (
    enforce_key_namespace,
    enforce_scan_pattern,
)
from app.modules.internal_api_platform.domain.sql.analyzer import analyze_readonly_query
from app.modules.internal_api_platform.domain.topology import (
    Base,
    DatabaseConnection,
    DatabaseEngine,
    Environment,
    OracleClientMode,
    OracleCompat,
    RedisConnection,
    RedisMode,
    RedisNode,
    ResourceKind,
)
from app.modules.internal_api_platform.infrastructure.config import (
    TopologyConfigError,
    load_platform_config,
)
from app.modules.internal_api_platform.infrastructure.db.oracle_client import (
    ThickInitState,
    assert_oracle_client_mode_ready,
    build_oracle_dsn,
    build_oracle_makedsn,
    ensure_oracle_client_initialized,
    reset_oracle_client_state_for_tests,
)
from app.modules.internal_api_platform.infrastructure.redis_gateway import RealRedisGateway
from app.modules.internal_api_platform.infrastructure.secrets import MappingSecretResolver
from app.modules.platform_config.application.validation import (
    PlatformConfigValidationError,
    normalize_oracle_database_config,
    normalize_redis_resource_config,
)


class RedisClusterConfigTests(unittest.TestCase):
    def test_standalone_default_from_yaml(self) -> None:
        config = textwrap.dedent(
            """
            environments:
              e:
                bases:
                  b:
                    engine: mysql
                    redis:
                      host: redis.local
                      port: 6379
            """
        )
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.yaml"
            path.write_text(config)
            topology, _ = load_platform_config(path, resolver=MappingSecretResolver({}))
        redis = topology.environment("e").base("b").redis  # type: ignore[union-attr]
        self.assertEqual(RedisMode.STANDALONE, redis.mode)
        self.assertEqual("redis.local", redis.host)

    def test_cluster_nodes_loaded(self) -> None:
        config = textwrap.dedent(
            """
            environments:
              e:
                bases:
                  b:
                    engine: mysql
                    redis:
                      mode: cluster
                      password: pw
                      nodes:
                        - { host: 10.0.0.1, port: 6379 }
                        - { host: 10.0.0.2, port: 6380 }
            """
        )
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.yaml"
            path.write_text(config)
            topology, _ = load_platform_config(path, resolver=MappingSecretResolver({}))
        redis = topology.environment("e").base("b").redis  # type: ignore[union-attr]
        self.assertEqual(RedisMode.CLUSTER, redis.mode)
        self.assertEqual(2, len(redis.nodes))
        self.assertEqual("10.0.0.1", redis.host)
        self.assertEqual(("10.0.0.1", "10.0.0.2"), tuple(n.host for n in redis.startup_nodes()))

    def test_cluster_missing_nodes_rejected(self) -> None:
        config = textwrap.dedent(
            """
            environments:
              e:
                bases:
                  b:
                    engine: mysql
                    redis:
                      mode: cluster
            """
        )
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.yaml"
            path.write_text(config)
            with self.assertRaises(TopologyConfigError):
                load_platform_config(path, resolver=MappingSecretResolver({}))

    def test_cluster_nonzero_db_rejected(self) -> None:
        config = textwrap.dedent(
            """
            environments:
              e:
                bases:
                  b:
                    engine: mysql
                    redis:
                      mode: cluster
                      db: 2
                      nodes:
                        - { host: 10.0.0.1, port: 6379 }
            """
        )
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.yaml"
            path.write_text(config)
            with self.assertRaises(TopologyConfigError):
                load_platform_config(path, resolver=MappingSecretResolver({}))

    def test_normalize_redis_resource_config_cluster(self) -> None:
        normalized = normalize_redis_resource_config(
            {"mode": "cluster", "nodes": [{"host": "a", "port": 6379}]}
        )
        self.assertEqual("cluster", normalized["mode"])
        with self.assertRaises(PlatformConfigValidationError):
            normalize_redis_resource_config({"mode": "cluster", "db": 1, "host": "a"})

    def _redis_binding(self, redis: RedisConnection) -> ResourceBinding:
        base = Base(code="b", engine=DatabaseEngine.MYSQL, redis=redis)
        return ResourceBinding(
            environment=Environment(code="e", bases={"b": base}),
            base=base,
            kind=ResourceKind.REDIS,
            workshop=None,
            engine=DatabaseEngine.MYSQL,
            redis=redis,
        )

    def test_gateway_selects_cluster_client(self) -> None:
        import sys
        import types

        binding = self._redis_binding(
            RedisConnection(
                host="10.0.0.1",
                port=6379,
                mode=RedisMode.CLUSTER,
                nodes=(RedisNode("10.0.0.1", 6379), RedisNode("10.0.0.2", 6379)),
                password="pw",
            )
        )
        fake_cluster = MagicMock(name="RedisClusterInstance")
        mock_cluster_cls = MagicMock(return_value=fake_cluster)
        redis_mod = types.ModuleType("redis")
        cluster_mod = types.ModuleType("redis.cluster")
        cluster_mod.RedisCluster = mock_cluster_cls  # type: ignore[attr-defined]
        with patch.dict(sys.modules, {"redis": redis_mod, "redis.cluster": cluster_mod}):
            client = RealRedisGateway()._connect(binding)
        self.assertIs(fake_cluster, client)
        mock_cluster_cls.assert_called_once()
        kwargs = mock_cluster_cls.call_args.kwargs
        self.assertEqual(
            [{"host": "10.0.0.1", "port": 6379}, {"host": "10.0.0.2", "port": 6379}],
            kwargs["startup_nodes"],
        )
        self.assertEqual("pw", kwargs["password"])

    def test_gateway_selects_standalone_client(self) -> None:
        import sys
        import types

        binding = self._redis_binding(
            RedisConnection(host="redis.local", port=6379, db=1, password="")
        )
        fake_client = MagicMock(name="Redis")
        redis_mod = types.ModuleType("redis")
        redis_mod.Redis = MagicMock(return_value=fake_client)  # type: ignore[attr-defined]
        with patch.dict(sys.modules, {"redis": redis_mod}):
            client = RealRedisGateway()._connect(binding)
        self.assertIs(fake_client, client)
        redis_mod.Redis.assert_called_once()  # type: ignore[attr-defined]
        self.assertEqual(1, redis_mod.Redis.call_args.kwargs["db"])  # type: ignore[attr-defined]

    def test_cluster_still_enforces_workshop_prefix(self) -> None:
        enforce_key_namespace("GL001:order:1", key_prefix="GL001:")
        with self.assertRaises(PolicyViolation):
            enforce_key_namespace("GL002:order:1", key_prefix="GL001:")
        enforce_scan_pattern("GL001:*", key_prefix="GL001:", scan_limit=200, limit=10)
        with self.assertRaises(PolicyViolation):
            enforce_scan_pattern("*", key_prefix="GL001:", scan_limit=200, limit=10)


class OracleCompatAndClientTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_oracle_client_state_for_tests()

    def tearDown(self) -> None:
        reset_oracle_client_state_for_tests()

    def test_modern_oracle_uses_fetch_first(self) -> None:
        analyzed = analyze_readonly_query(
            "select * from GL001_EBR_order",
            engine=DatabaseEngine.ORACLE,
            max_rows=10,
            table_prefix="gl001_ebr_",
            oracle_compat=OracleCompat.MODERN,
        )
        self.assertIn("FETCH FIRST 10 ROWS ONLY", analyzed.sql)
        self.assertNotIn("ROWNUM", analyzed.sql)

    def test_legacy_oracle_uses_rownum(self) -> None:
        analyzed = analyze_readonly_query(
            "select * from GL001_EBR_order",
            engine=DatabaseEngine.ORACLE,
            max_rows=10,
            table_prefix="gl001_ebr_",
            oracle_compat=OracleCompat.LEGACY,
        )
        self.assertIn("ROWNUM <= 10", analyzed.sql)
        self.assertNotIn("FETCH FIRST", analyzed.sql)

    def test_oracle_yaml_fields(self) -> None:
        config = textwrap.dedent(
            """
            environments:
              e:
                bases:
                  b:
                    engine: oracle
                    database:
                      host: ora.local
                      port: 1521
                      database: ORCL
                      user: u
                      password: p
                      oracle_client_mode: thick
                      oracle_compat: legacy
                      use_sid: true
            """
        )
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.yaml"
            path.write_text(config)
            topology, _ = load_platform_config(path, resolver=MappingSecretResolver({}))
        db = topology.environment("e").base("b").database  # type: ignore[union-attr]
        self.assertEqual(OracleClientMode.THICK, db.oracle_client_mode)
        self.assertEqual(OracleCompat.LEGACY, db.oracle_compat)
        self.assertTrue(db.use_sid)

    def test_dsn_sid_vs_service(self) -> None:
        fake = MagicMock()
        fake.makedsn = MagicMock(side_effect=lambda *a, **k: f"dsn:{k}")
        self.assertEqual(
            "dsn:{'sid': 'ORCL'}",
            build_oracle_makedsn(fake, host="h", port=1521, database="ORCL", use_sid=True),
        )
        self.assertEqual(
            "dsn:{'service_name': 'ORCL'}",
            build_oracle_makedsn(fake, host="h", port=1521, database="ORCL", use_sid=False),
        )
        self.assertEqual(
            "(DESCRIPTION=...)",
            build_oracle_dsn(
                host="h",
                port=1521,
                database="ORCL",
                connect_descriptor="(DESCRIPTION=...)",
            ),
        )

    def test_thick_required_without_client_fails(self) -> None:
        with patch(
            "app.modules.internal_api_platform.infrastructure.db.oracle_client.resolve_oracle_client_lib_dir",
            return_value="",
        ):
            reset_oracle_client_state_for_tests()
            result = ensure_oracle_client_initialized()
            self.assertEqual(ThickInitState.THIN_ONLY, result.state)
            with self.assertRaises(ResolutionError):
                assert_oracle_client_mode_ready(OracleClientMode.THICK)

    def test_auto_allows_thin_when_no_client(self) -> None:
        with patch(
            "app.modules.internal_api_platform.infrastructure.db.oracle_client.resolve_oracle_client_lib_dir",
            return_value="",
        ):
            reset_oracle_client_state_for_tests()
            assert_oracle_client_mode_ready(OracleClientMode.AUTO)

    def test_normalize_oracle_database_config(self) -> None:
        normalized = normalize_oracle_database_config(
            {"oracle_client_mode": "THICK", "oracle_compat": "legacy", "use_sid": "true"}
        )
        self.assertEqual("thick", normalized["oracle_client_mode"])
        self.assertEqual("legacy", normalized["oracle_compat"])
        self.assertTrue(normalized["use_sid"])


class DatabaseConnectionDefaultsTests(unittest.TestCase):
    def test_defaults_preserve_compat(self) -> None:
        db = DatabaseConnection(
            host="h", port=1521, database="ORCL", user="u", password="p"
        )
        self.assertEqual(OracleClientMode.AUTO, db.oracle_client_mode)
        self.assertEqual(OracleCompat.MODERN, db.oracle_compat)
        self.assertFalse(db.use_sid)


if __name__ == "__main__":
    unittest.main()
