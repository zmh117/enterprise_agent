from __future__ import annotations

import os
import unittest

_RUN_REDIS = os.getenv("RUN_REDIS_CLUSTER_INTEGRATION") == "1"
_RUN_ORACLE = os.getenv("RUN_ORACLE_THICK_INTEGRATION") == "1"


@unittest.skipUnless(_RUN_REDIS, "set RUN_REDIS_CLUSTER_INTEGRATION=1 against a live cluster")
class RedisClusterIntegrationTests(unittest.TestCase):
    """Opt-in live Redis Cluster smoke test.

    Env:
      REDIS_CLUSTER_NODES=host1:6379,host2:6379
      REDIS_PASSWORD=...
      REDIS_TEST_KEY=GL001:smoke
      REDIS_TEST_PREFIX=GL001:
    """

    def test_cluster_get_within_prefix(self) -> None:
        from app.modules.internal_api_platform.domain.addressing import ResourceBinding
        from app.modules.internal_api_platform.domain.redis_policy import enforce_key_namespace
        from app.modules.internal_api_platform.domain.topology import (
            Base,
            DatabaseEngine,
            Environment,
            RedisConnection,
            RedisMode,
            RedisNode,
            ResourceKind,
        )
        from app.modules.internal_api_platform.infrastructure.redis_gateway import RealRedisGateway

        nodes_raw = os.getenv("REDIS_CLUSTER_NODES", "127.0.0.1:6379")
        nodes = []
        for part in nodes_raw.split(","):
            host, _, port = part.partition(":")
            nodes.append(RedisNode(host=host.strip(), port=int(port or 6379)))
        redis = RedisConnection(
            host=nodes[0].host,
            port=nodes[0].port,
            mode=RedisMode.CLUSTER,
            nodes=tuple(nodes),
            password=os.getenv("REDIS_PASSWORD", ""),
        )
        key = os.getenv("REDIS_TEST_KEY", "GL001:smoke")
        prefix = os.getenv("REDIS_TEST_PREFIX", "GL001:")
        enforce_key_namespace(key, key_prefix=prefix)
        base = Base(code="b", engine=DatabaseEngine.MYSQL, redis=redis)
        binding = ResourceBinding(
            environment=Environment(code="e", bases={"b": base}),
            base=base,
            kind=ResourceKind.REDIS,
            workshop=None,
            engine=DatabaseEngine.MYSQL,
            redis=redis,
        )
        result = RealRedisGateway().get(binding, key)
        self.assertIn("key", result.summary)


@unittest.skipUnless(_RUN_ORACLE, "set RUN_ORACLE_THICK_INTEGRATION=1 against a live Oracle")
class OracleThickIntegrationTests(unittest.TestCase):
    """Opt-in live Oracle thick/legacy smoke test.

    Requires Instant Client on ORACLE_CLIENT_LIB_DIR and a reachable DB.
    Env: ORACLE_HOST / ORACLE_PORT / ORACLE_SERVICE / ORACLE_USER / ORACLE_PASSWORD
         ORACLE_USE_SID=1 ORACLE_COMPAT=legacy
    """

    def test_thick_readonly_select(self) -> None:
        from app.modules.internal_api_platform.domain.addressing import ResourceBinding
        from app.modules.internal_api_platform.domain.sql.analyzer import analyze_readonly_query
        from app.modules.internal_api_platform.domain.topology import (
            Base,
            DatabaseConnection,
            DatabaseEngine,
            Environment,
            OracleClientMode,
            OracleCompat,
            ResourceKind,
        )
        from app.modules.internal_api_platform.infrastructure.db.drivers import OracleExecutor
        from app.modules.internal_api_platform.infrastructure.db.oracle_client import (
            ensure_oracle_client_initialized,
            reset_oracle_client_state_for_tests,
        )

        reset_oracle_client_state_for_tests()
        init = ensure_oracle_client_initialized()
        self.assertEqual("thick", init.state.value)

        use_sid = os.getenv("ORACLE_USE_SID", "0") in {"1", "true", "yes"}
        compat = OracleCompat(os.getenv("ORACLE_COMPAT", "legacy"))
        db = DatabaseConnection(
            host=os.getenv("ORACLE_HOST", "localhost"),
            port=int(os.getenv("ORACLE_PORT", "1521")),
            database=os.getenv("ORACLE_SERVICE", "ORCL"),
            user=os.getenv("ORACLE_USER", "system"),
            password=os.getenv("ORACLE_PASSWORD", "oracle"),
            oracle_client_mode=OracleClientMode.THICK,
            oracle_compat=compat,
            use_sid=use_sid,
        )
        base = Base(code="main", engine=DatabaseEngine.ORACLE, database=db)
        binding = ResourceBinding(
            environment=Environment(code="local", bases={"main": base}),
            base=base,
            kind=ResourceKind.DATABASE,
            workshop=None,
            engine=DatabaseEngine.ORACLE,
            database=db,
        )
        sql = os.getenv("ORACLE_TEST_SQL", "SELECT 1 AS n FROM dual")
        analyzed = analyze_readonly_query(
            sql,
            engine=DatabaseEngine.ORACLE,
            max_rows=5,
            table_prefix=None,
            oracle_compat=compat,
        )
        executed = OracleExecutor().execute(
            binding, analyzed.sql, timeout_seconds=15, max_rows=5
        )
        self.assertGreaterEqual(len(executed.rows), 1)


if __name__ == "__main__":
    unittest.main()
