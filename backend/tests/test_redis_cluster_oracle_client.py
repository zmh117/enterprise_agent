from __future__ import annotations

import unittest
import json
from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from app.modules.mcp_tool_runtime.domain.addressing import ResourceBinding
from app.modules.mcp_tool_runtime.domain.errors import PolicyViolation, ResolutionError
from app.modules.mcp_tool_runtime.domain.redis_policy import (
    enforce_key_namespace,
    enforce_scan_pattern,
)
from app.modules.mcp_tool_runtime.domain.sql.analyzer import analyze_readonly_query
from app.modules.mcp_tool_runtime.domain.topology import (
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
from app.modules.mcp_tool_runtime.infrastructure.db.oracle_client import (
    ThickInitState,
    assert_oracle_client_mode_ready,
    build_oracle_dsn,
    build_oracle_makedsn,
    ensure_oracle_client_initialized,
    inspect_oracle_client,
    reset_oracle_client_state_for_tests,
)
from app.modules.mcp_tool_runtime.infrastructure.redis_gateway import RealRedisGateway
from app.shared.exceptions import ToolPolicyError
from app.modules.platform_config.application.validation import (
    PlatformConfigValidationError,
    normalize_oracle_database_config,
    normalize_redis_resource_config,
)


class RedisClusterConfigTests(unittest.TestCase):
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
        cluster_mod.ClusterNode = lambda host, port: SimpleNamespace(host=host, port=port)  # type: ignore[attr-defined]
        with patch.dict(sys.modules, {"redis": redis_mod, "redis.cluster": cluster_mod}):
            client = RealRedisGateway()._connect(binding)
        self.assertIs(fake_cluster, client)
        mock_cluster_cls.assert_called_once()
        kwargs = mock_cluster_cls.call_args.kwargs
        self.assertEqual(
            [{"host": "10.0.0.1", "port": 6379}, {"host": "10.0.0.2", "port": 6379}],
            [{"host": node.host, "port": node.port} for node in kwargs["startup_nodes"]],
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

    def test_gateway_applies_controlled_tls_settings(self) -> None:
        import sys
        import types

        binding = self._redis_binding(
            RedisConnection(
                host="redis.internal",
                port=6380,
                db=2,
                username="reader",
                password="pw",
                tls_enabled=True,
                tls_verify_certificate=True,
            )
        )
        fake_client = MagicMock(name="Redis")
        redis_mod = types.ModuleType("redis")
        redis_mod.Redis = MagicMock(  # type: ignore[attr-defined]
            return_value=fake_client
        )
        with patch.dict(sys.modules, {"redis": redis_mod}):
            client = RealRedisGateway()._connect(binding)
        self.assertIs(fake_client, client)
        kwargs = redis_mod.Redis.call_args.kwargs  # type: ignore[attr-defined]
        self.assertTrue(kwargs["ssl"])
        self.assertEqual("required", kwargs["ssl_cert_reqs"])
        self.assertTrue(kwargs["ssl_check_hostname"])
        self.assertEqual("reader", kwargs["username"])

    def test_gateway_drains_terminal_oversized_batch_before_finishing(self) -> None:
        binding = self._redis_binding(RedisConnection(host="redis.local", port=6379))
        client = MagicMock()
        client.scan.return_value = (0, ["GL001:3", "GL001:1", "GL001:2"])
        gateway = RealRedisGateway()
        with patch.object(gateway, "_connect", return_value=client):
            response = gateway.scan(binding, "GL001:*", 2)
            second = gateway.scan(binding, "GL001:*", 2, response.metadata["next_provider_cursor"])
        self.assertEqual(2, client.scan.call_count)
        client.scan.assert_called_with(cursor=0, match="GL001:*", count=2)
        self.assertEqual(["GL001:1", "GL001:2"], response.summary["keys"])
        self.assertTrue(response.truncated)
        self.assertEqual(["GL001:3"], second.summary["keys"])
        self.assertFalse(second.truncated)
        self.assertEqual(0, second.metadata["next_provider_cursor"])

    def test_gateway_scans_each_primary_with_scalar_cursor_and_drains_remainders(self) -> None:
        binding = self._redis_binding(
            RedisConnection(
                host="10.0.0.1",
                port=6379,
                mode=RedisMode.CLUSTER,
                nodes=(RedisNode("10.0.0.1", 6379), RedisNode("10.0.0.2", 6379)),
            )
        )
        client = MagicMock()
        node_a, node_b = (
            SimpleNamespace(name="private-a:6379"),
            SimpleNamespace(name="private-b:6379"),
        )
        client.get_primaries.return_value = [node_b, node_a]
        client.scan.side_effect = [
            ({node_a.name: 12}, []),
            ({node_a.name: 0}, ["GL001:3", "GL001:2", "GL001:1"]),
            ({node_a.name: 0}, ["GL001:1", "GL001:2", "GL001:3"]),
            ({node_b.name: 0}, ["GL001:4"]),
        ]
        gateway = RealRedisGateway()
        with patch.object(gateway, "_connect", return_value=client):
            cursor: object = 0
            results = []
            for _ in range(4):
                response = gateway.scan(binding, "GL001:*", 2, cursor)
                results.extend(response.summary["keys"])
                cursor = response.metadata["next_provider_cursor"]
                self.assertNotIn("private-", json.dumps(cursor))
                self.assertNotIn("GL001:", json.dumps(cursor))
        self.assertEqual(["GL001:1", "GL001:2", "GL001:3", "GL001:4"], results)
        self.assertEqual(0, cursor)
        self.assertFalse(response.truncated)
        self.assertEqual(
            [0, 12, 12, 0], [call.kwargs["cursor"] for call in client.scan.call_args_list]
        )
        self.assertEqual(
            [node_a, node_a, node_a, node_b],
            [call.kwargs["target_nodes"] for call in client.scan.call_args_list],
        )
        self.assertEqual(4, client.close.call_count)

    def test_gateway_rejects_changed_replay_batch_and_closes_client(self) -> None:
        binding = self._redis_binding(RedisConnection(host="redis.local", port=6379))
        client = MagicMock()
        client.scan.side_effect = [(0, ["a", "b", "c"]), (0, ["a", "b", "d"])]
        gateway = RealRedisGateway()
        with patch.object(gateway, "_connect", return_value=client):
            first = gateway.scan(binding, "GL001:*", 2)
            with self.assertRaises(ToolPolicyError) as raised:
                gateway.scan(binding, "GL001:*", 2, first.metadata["next_provider_cursor"])
        self.assertEqual("mcp_pagination_cursor_stale", raised.exception.error_code)
        self.assertEqual(2, client.close.call_count)

    def test_gateway_rejects_changed_topology_before_scan(self) -> None:
        binding = self._redis_binding(
            RedisConnection(host="cluster", port=6379, mode=RedisMode.CLUSTER)
        )
        client = MagicMock()
        client.get_primaries.side_effect = [
            [SimpleNamespace(name="a:6379"), SimpleNamespace(name="b:6379")],
            [SimpleNamespace(name="a:6379"), SimpleNamespace(name="c:6379")],
        ]
        client.scan.return_value = ({"a:6379": 0}, [])
        gateway = RealRedisGateway()
        with patch.object(gateway, "_connect", return_value=client):
            first = gateway.scan(binding, "GL001:*", 2)
            self.assertTrue(first.truncated)
            with self.assertRaises(ToolPolicyError) as raised:
                gateway.scan(binding, "GL001:*", 2, first.metadata["next_provider_cursor"])
        self.assertEqual("mcp_pagination_cursor_stale", raised.exception.error_code)
        client.scan.assert_called_once()
        self.assertEqual(2, client.close.call_count)

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

    def test_modern_legacy_flag_cannot_enable_oracle_12c_syntax(self) -> None:
        analyzed = analyze_readonly_query(
            "select * from GL001_EBR_order",
            engine=DatabaseEngine.ORACLE,
            max_rows=10,
            table_prefix="gl001_ebr_",
            oracle_compat=OracleCompat.MODERN,
        )
        self.assertIn("ROWNUM <= 10", analyzed.sql)
        self.assertNotIn("FETCH FIRST", analyzed.sql)

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
        with self.assertRaises(ResolutionError):
            build_oracle_dsn(
                host="h",
                port=1521,
                database="ORCL",
                connect_descriptor="(DESCRIPTION=...)",
            )

    def test_thick_required_without_client_fails(self) -> None:
        with patch(
            "app.modules.mcp_tool_runtime.infrastructure.db.oracle_client.resolve_oracle_client_lib_dir",
            return_value="",
        ):
            reset_oracle_client_state_for_tests()
            result = ensure_oracle_client_initialized()
            self.assertEqual(ThickInitState.THIN_ONLY, result.state)
            with self.assertRaises(ResolutionError):
                assert_oracle_client_mode_ready(OracleClientMode.THICK)

    def test_auto_cannot_fall_back_to_thin_when_no_client(self) -> None:
        with patch(
            "app.modules.mcp_tool_runtime.infrastructure.db.oracle_client.resolve_oracle_client_lib_dir",
            return_value="",
        ):
            reset_oracle_client_state_for_tests()
            with self.assertRaises(ResolutionError):
                assert_oracle_client_mode_ready(OracleClientMode.AUTO)

    def test_client_architecture_must_be_64_bit_19c_and_match_runtime(
        self,
    ) -> None:
        with TemporaryDirectory() as tmp:
            library = Path(tmp) / "libclntsh.so.19.1"
            header = bytearray(20)
            header[:4] = b"\x7fELF"
            header[4] = 2
            header[5] = 1
            header[18:20] = (62).to_bytes(2, "little")
            library.write_bytes(header)
            with patch(
                "app.modules.mcp_tool_runtime.infrastructure.db.oracle_client.platform.machine",
                return_value="x86_64",
            ):
                self.assertEqual(
                    ("19c", "x86_64"),
                    inspect_oracle_client(tmp),
                )

    def test_client_architecture_mismatch_fails_closed(self) -> None:
        with TemporaryDirectory() as tmp:
            library = Path(tmp) / "libclntsh.so.19.1"
            header = bytearray(20)
            header[:4] = b"\x7fELF"
            header[4] = 2
            header[5] = 1
            header[18:20] = (62).to_bytes(2, "little")
            library.write_bytes(header)
            with (
                patch(
                    "app.modules.mcp_tool_runtime.infrastructure.db.oracle_client.platform.machine",
                    return_value="aarch64",
                ),
                self.assertRaises(ResolutionError),
            ):
                inspect_oracle_client(tmp)

    def test_normalize_oracle_database_config(self) -> None:
        normalized = normalize_oracle_database_config(
            {"oracle_client_mode": "THICK", "oracle_compat": "legacy", "use_sid": "true"}
        )
        self.assertEqual("thick", normalized["oracle_client_mode"])
        self.assertEqual("legacy", normalized["oracle_compat"])
        self.assertTrue(normalized["use_sid"])


class DatabaseConnectionDefaultsTests(unittest.TestCase):
    def test_defaults_enforce_oracle_11g_contract(self) -> None:
        db = DatabaseConnection(host="h", port=1521, database="ORCL", user="u", password="p")
        self.assertEqual(OracleClientMode.THICK, db.oracle_client_mode)
        self.assertEqual(OracleCompat.LEGACY, db.oracle_compat)
        self.assertFalse(db.use_sid)


if __name__ == "__main__":
    unittest.main()
