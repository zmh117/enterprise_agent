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

    def test_allows_readonly_cte_and_comment_prefix(self) -> None:
        analyzed = analyze_readonly_query(
            """
            /* diagnostic */ WITH current_orders AS (
                SELECT * FROM GL001_EBR_order
            )
            SELECT * FROM current_orders
            """,
            engine=DatabaseEngine.MYSQL,
            max_rows=50,
            table_prefix="GL001_EBR_",
        )
        self.assertIn("WITH current_orders", analyzed.sql)

    def test_allows_aliases_and_checks_every_joined_physical_table(self) -> None:
        analyzed = analyze_readonly_query(
            """
            SELECT header.order_no
              FROM GL001_ORDER header
              JOIN GL001_ORDER_LINE line
                ON line.order_no = header.order_no
            """,
            engine=DatabaseEngine.MYSQL,
            max_rows=50,
            table_prefix="GL001_",
        )
        self.assertEqual(
            ["GL001_ORDER", "GL001_ORDER_LINE"],
            analyzed.tables,
        )
        with self.assertRaises(PolicyViolation):
            analyze_readonly_query(
                """
                SELECT *
                  FROM GL001_ORDER header
                  JOIN GL002_ORDER other
                    ON other.id = header.id
                """,
                engine=DatabaseEngine.MYSQL,
                max_rows=50,
                table_prefix="GL001_",
            )

    def test_rejects_dynamic_table_references_before_execution(self) -> None:
        for engine, sql in (
            (DatabaseEngine.MYSQL, "select * from @table_name"),
            (DatabaseEngine.SQLSERVER, "select * from @table_name"),
            (DatabaseEngine.MYSQL, "select * from identifier(:table_name)"),
            (
                DatabaseEngine.SQLSERVER,
                "select * from openquery(server, 'select * from GL001_ORDER')",
            ),
        ):
            with self.subTest(engine=engine.value, sql=sql):
                with self.assertRaises(PolicyViolation):
                    analyze_readonly_query(
                        sql,
                        engine=engine,
                        max_rows=50,
                        table_prefix="GL001_",
                    )

    def test_qualified_tables_must_remain_in_frozen_database_and_schema(self) -> None:
        mysql = analyze_readonly_query(
            "select * from APPDB.GL001_ORDER",
            engine=DatabaseEngine.MYSQL,
            max_rows=50,
            table_prefix="GL001_",
            allowed_database="APPDB",
        )
        self.assertEqual(["GL001_ORDER"], mysql.tables)
        sqlserver = analyze_readonly_query(
            "select * from APPDB.dbo.GL001_ORDER",
            engine=DatabaseEngine.SQLSERVER,
            max_rows=50,
            table_prefix="GL001_",
            allowed_database="APPDB",
            allowed_schema="dbo",
        )
        self.assertEqual(["GL001_ORDER"], sqlserver.tables)
        oracle = analyze_readonly_query(
            "select * from APP_OWNER.GL001_ORDER",
            engine=DatabaseEngine.ORACLE,
            max_rows=50,
            table_prefix="GL001_",
            allowed_schema="app_owner",
        )
        self.assertEqual(["GL001_ORDER"], oracle.tables)

        for engine, sql, options in (
            (
                DatabaseEngine.MYSQL,
                "select * from OTHERDB.GL001_ORDER",
                {"allowed_database": "APPDB"},
            ),
            (
                DatabaseEngine.SQLSERVER,
                "select * from OTHERDB.dbo.GL001_ORDER",
                {"allowed_database": "APPDB", "allowed_schema": "dbo"},
            ),
            (
                DatabaseEngine.ORACLE,
                "select * from OTHER_OWNER.GL001_ORDER",
                {"allowed_schema": "APP_OWNER"},
            ),
        ):
            with self.subTest(engine=engine.value, sql=sql):
                with self.assertRaises(PolicyViolation):
                    analyze_readonly_query(
                        sql,
                        engine=engine,
                        max_rows=50,
                        table_prefix="GL001_",
                        **options,
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
        self.assertIn("ROWNUM <= 10", analyzed.sql)
        self.assertNotIn("FETCH FIRST", analyzed.sql)

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

    def test_real_namespace_examples_allow_multiple_prefixes_and_reject_cross_workshop(
        self,
    ) -> None:
        prefixes = (
            "cr999.crmes.CRMES_TEST_GL#GL001@$",
            "cr999.crmes.CRMES_ARCHIVE_GL#GL001@$",
        )
        for key in (
            "cr999.crmes.CRMES_TEST_GL#GL001@$EBRDataText.809901890274822.Sheet4.rows",
            "cr999.crmes.CRMES_TEST_GL#GL001@$[WEIGH]:wo.20250627MAOYAN10-yapi5:weigh_id.list",
            "cr999.crmes.CRMES_TEST_GL#GL001@$[BATCH_RECORD]:674351510281286:exec_param",
            "cr999.crmes.CRMES_ARCHIVE_GL#GL001@$[BATCH_RECORD]:675454427238982:states",
        ):
            enforce_key_namespace(key, key_prefixes=prefixes)
        with self.assertRaises(PolicyViolation):
            enforce_key_namespace(
                "cr999.crmes.CRMES_TEST_CZ#CZ002@$[WEIGH]:wo.20260410-11:weigh_id.list",
                key_prefixes=prefixes,
            )

    def test_scan_requires_complete_prefix_before_glob_and_bounds_results(self) -> None:
        prefixes = ("cr999.crmes.CRMES_TEST_GL#GL001@$",)
        self.assertEqual(
            "cr999.crmes.CRMES_TEST_GL#GL001@$\\[BATCH_RECORD\\]:*",
            enforce_scan_pattern(
                "cr999.crmes.CRMES_TEST_GL#GL001@$[BATCH_RECORD]:*",
                key_prefixes=prefixes,
                scan_limit=200,
                limit=50,
            ),
        )
        for pattern in (
            "*GL001*",
            "?cr999.crmes.CRMES_TEST_GL#GL001@$*",
            "cr999.crmes.CRMES_TEST_GL#GL001@$order?",
            "^cr999.*GL001$",
            "cr999.crmes.CRMES_TEST_CZ#CZ002@$*",
        ):
            with self.subTest(pattern=pattern):
                with self.assertRaises(PolicyViolation):
                    enforce_scan_pattern(
                        pattern,
                        key_prefixes=prefixes,
                        scan_limit=200,
                        limit=50,
                    )


class LokiPolicyTests(unittest.TestCase):
    def test_injects_workshop_label(self) -> None:
        selector = build_effective_selector(
            {"service": "order-service"},
            mandatory_conditions=(("customer", "sanjiu-test1"),),
            require_mandatory=True,
        )
        self.assertEqual(
            {"customer": "sanjiu-test1", "service": "order-service"},
            selector,
        )

    def test_rejects_unknown_label(self) -> None:
        with self.assertRaises(PolicyViolation):
            build_effective_selector({"namespace": "x"})

    def test_rejects_override_or_fuzzy_diagnostic_filter(self) -> None:
        with self.assertRaises(PolicyViolation):
            build_effective_selector(
                {"customer": "other"},
                mandatory_conditions=(("customer", "sanjiu-test1"),),
                require_mandatory=True,
            )
        with self.assertRaises(PolicyViolation):
            build_effective_selector(
                {"logtype": "error.*"},
                mandatory_conditions=(("customer", "sanjiu-test1"),),
                require_mandatory=True,
            )


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
