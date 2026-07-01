from __future__ import annotations

import unittest

from app.modules.internal_api_platform.domain.access import (
    AccessPolicy,
    AccessScope,
    ScopeRule,
)
from app.modules.internal_api_platform.domain.addressing import TargetRef
from app.modules.internal_api_platform.domain.errors import (
    AuthorizationError,
    PolicyViolation,
)
from app.modules.internal_api_platform.domain.loki_policy import build_effective_selector
from app.modules.internal_api_platform.domain.redis_policy import (
    enforce_key_namespace,
    enforce_scan_pattern,
)
from app.modules.internal_api_platform.domain.sql.analyzer import analyze_readonly_query
from app.modules.internal_api_platform.domain.topology import (
    DatabaseEngine,
    ResourceKind,
    Workshop,
)


class SqlSafetyTests(unittest.TestCase):
    def test_allows_prefixed_select_and_bounds_rows(self) -> None:
        analyzed = analyze_readonly_query(
            "select * from GL001_EBR_order where status='WAIT'",
            engine=DatabaseEngine.MYSQL,
            max_rows=50,
            table_prefix="GL001_EBR_",
        )
        self.assertIn("LIMIT 50", analyzed.sql)
        self.assertEqual(["GL001_EBR_order"], analyzed.tables)

    def test_respects_smaller_existing_limit(self) -> None:
        analyzed = analyze_readonly_query(
            "select * from GL001_EBR_order limit 5",
            engine=DatabaseEngine.MYSQL,
            max_rows=100,
            table_prefix="GL001_EBR_",
        )
        self.assertEqual(5, analyzed.row_limit)

    def test_rejects_cross_workshop_table(self) -> None:
        with self.assertRaises(PolicyViolation):
            analyze_readonly_query(
                "select * from GL002_EBR_order",
                engine=DatabaseEngine.MYSQL,
                max_rows=50,
                table_prefix="GL001_EBR_",
            )

    def test_rejects_missing_prefix(self) -> None:
        with self.assertRaises(PolicyViolation):
            analyze_readonly_query(
                "select * from order_header",
                engine=DatabaseEngine.MYSQL,
                max_rows=50,
                table_prefix="GL001_EBR_",
            )

    def test_rejects_write_statements(self) -> None:
        for sql in (
            "insert into GL001_EBR_order values(1)",
            "update GL001_EBR_order set status='x'",
            "delete from GL001_EBR_order",
            "drop table GL001_EBR_order",
            "select * from GL001_EBR_order for update",
            "select 1; select 2",
        ):
            with self.assertRaises(PolicyViolation, msg=sql):
                analyze_readonly_query(
                    sql,
                    engine=DatabaseEngine.MYSQL,
                    max_rows=50,
                    table_prefix="GL001_EBR_",
                )

    def test_rejects_select_into_on_sqlserver(self) -> None:
        with self.assertRaises(PolicyViolation):
            analyze_readonly_query(
                "select * into newt from t",
                engine=DatabaseEngine.SQLSERVER,
                max_rows=50,
                table_prefix=None,
            )

    def test_rejects_plsql_block_on_oracle(self) -> None:
        with self.assertRaises(PolicyViolation):
            analyze_readonly_query(
                "begin null; end;",
                engine=DatabaseEngine.ORACLE,
                max_rows=50,
                table_prefix=None,
            )

    def test_oracle_case_folding_prefix_match(self) -> None:
        analyzed = analyze_readonly_query(
            "select * from GL001_EBR_order",
            engine=DatabaseEngine.ORACLE,
            max_rows=10,
            table_prefix="gl001_ebr_",
        )
        self.assertIn("FETCH FIRST 10 ROWS ONLY", analyzed.sql)

    def test_sqlserver_uses_top(self) -> None:
        analyzed = analyze_readonly_query(
            "select * from t",
            engine=DatabaseEngine.SQLSERVER,
            max_rows=5,
            table_prefix=None,
        )
        self.assertIn("TOP 5", analyzed.sql)


class RedisPolicyTests(unittest.TestCase):
    def test_key_must_match_prefix(self) -> None:
        enforce_key_namespace("GL001:order:1", key_prefix="GL001:")
        with self.assertRaises(PolicyViolation):
            enforce_key_namespace("GL002:order:1", key_prefix="GL001:")

    def test_scan_pattern_bounded_and_prefixed(self) -> None:
        enforce_scan_pattern("GL001:order:*", key_prefix="GL001:", scan_limit=200, limit=50)
        with self.assertRaises(PolicyViolation):
            enforce_scan_pattern("*", key_prefix="GL001:", scan_limit=200, limit=50)
        with self.assertRaises(PolicyViolation):
            enforce_scan_pattern("GL002:*", key_prefix="GL001:", scan_limit=200, limit=50)
        with self.assertRaises(PolicyViolation):
            enforce_scan_pattern("GL001:*", key_prefix="GL001:", scan_limit=200, limit=999)


class LokiPolicyTests(unittest.TestCase):
    def test_injects_workshop_label(self) -> None:
        workshop = Workshop(
            code="GL001",
            table_prefix="GL001_EBR_",
            redis_key_prefix="GL001:",
            loki_label={"workshop": "GL001"},
        )
        selector = build_effective_selector({"service": "order-service"}, workshop=workshop)
        self.assertEqual({"service": "order-service", "workshop": "GL001"}, selector)

    def test_rejects_unknown_label(self) -> None:
        with self.assertRaises(PolicyViolation):
            build_effective_selector({"namespace": "x"}, workshop=None)


class AccessPolicyTests(unittest.TestCase):
    def test_wildcard_and_specific_grants(self) -> None:
        policy = AccessPolicy(
            scopes={
                "alice": AccessScope(
                    rules=[ScopeRule(environment="sanjiu", base="guanlan", workshop="GL001")]
                ),
                "bob": AccessScope(rules=[ScopeRule(environment="sanjiu")]),
            }
        )
        target = TargetRef("sanjiu", "guanlan", ResourceKind.DATABASE, "GL001")
        other = TargetRef("sanjiu", "guanlan", ResourceKind.DATABASE, "GL002")
        policy.authorize(user_id="alice", target=target)
        policy.authorize(user_id="bob", target=other)
        with self.assertRaises(AuthorizationError):
            policy.authorize(user_id="alice", target=other)
        with self.assertRaises(AuthorizationError):
            policy.authorize(user_id="", target=target)
        with self.assertRaises(AuthorizationError):
            policy.authorize(user_id="carol", target=target)


if __name__ == "__main__":
    unittest.main()
