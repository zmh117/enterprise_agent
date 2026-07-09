from __future__ import annotations

import sys
import types
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.modules.internal_api_platform.app import create_app
from app.modules.internal_api_platform.application.platform_service import PlatformService
from app.modules.internal_api_platform.domain.access import AccessPolicy, AccessScope, ScopeRule
from app.modules.internal_api_platform.domain.addressing import ResourceBinding
from app.modules.internal_api_platform.domain.errors import (
    PolicyViolation,
    ResolutionError,
    UpstreamUnavailable,
)
from app.modules.internal_api_platform.domain.schema_directory import (
    SchemaColumn,
    SchemaDirectory,
    SchemaTable,
)
from app.modules.internal_api_platform.domain.topology import (
    Base,
    DatabaseConnection,
    DatabaseEngine,
    Environment,
    OracleCompat,
    ResourceKind,
    Topology,
)
from app.modules.internal_api_platform.infrastructure.db.executor import FakeQueryExecutor
from app.modules.internal_api_platform.infrastructure.db.schema_directory import (
    FakeSchemaInspector,
    MySqlSchemaInspector,
    OracleSchemaInspector,
    SchemaInspectorFactory,
    SqlServerSchemaInspector,
    UnsupportedSchemaInspector,
)
from app.modules.internal_api_platform.infrastructure.loki_gateway import FakeLokiClient
from app.modules.internal_api_platform.infrastructure.redis_gateway import FakeRedisGateway
from app.modules.internal_api_platform.infrastructure.registry import TopologyRegistry


class _ScriptedCursor:
    def __init__(self, results: list[list[tuple[Any, ...]]]) -> None:
        self._results = results
        self._current: list[tuple[Any, ...]] = []
        self.calls: list[tuple[str, Any]] = []
        self.closed = False

    def execute(self, sql: str, params: Any = None, **kwargs: Any) -> None:
        effective_params = params if params is not None else kwargs
        self.calls.append((sql, effective_params))
        self._current = self._results[len(self.calls) - 1]

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._current)

    def close(self) -> None:
        self.closed = True


class _FakeConnection:
    def __init__(self, cursor: _ScriptedCursor) -> None:
        self._cursor = cursor
        self.closed = False
        self.call_timeout = 0

    def cursor(self) -> _ScriptedCursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


def _binding(
    engine: DatabaseEngine,
    *,
    schema: str = "",
    user: str = "reader",
    host: str = "private-db.internal",
    password: str = "top-secret-password",
) -> ResourceBinding:
    db = DatabaseConnection(
        host=host,
        port=1521 if engine is DatabaseEngine.ORACLE else 1433,
        database="APPDB",
        user=user,
        password=password,
        schema=schema,
    )
    base = Base(code="main", engine=engine, database=db)
    return ResourceBinding(
        environment=Environment(code="prod", bases={"main": base}),
        base=base,
        kind=ResourceKind.DATABASE,
        workshop=None,
        engine=engine,
        database=db,
    )


class SchemaInspectorFactoryTests(unittest.TestCase):
    def test_routes_each_registered_engine_without_fallback(self) -> None:
        mysql = MagicMock()
        sqlserver = MagicMock()
        oracle = MagicMock()
        factory = SchemaInspectorFactory(
            {
                DatabaseEngine.MYSQL: mysql,
                DatabaseEngine.SQLSERVER: sqlserver,
                DatabaseEngine.ORACLE: oracle,
            }
        )

        self.assertIs(mysql, factory.for_engine(DatabaseEngine.MYSQL))
        self.assertIs(sqlserver, factory.for_engine(DatabaseEngine.SQLSERVER))
        self.assertIs(oracle, factory.for_engine(DatabaseEngine.ORACLE))

    def test_registers_inspector_and_returns_explicit_unsupported(self) -> None:
        factory = SchemaInspectorFactory()
        unsupported = factory.for_engine(DatabaseEngine.ORACLE)
        self.assertIsInstance(unsupported, UnsupportedSchemaInspector)
        result = unsupported.read(
            _binding(DatabaseEngine.ORACLE),
            table_prefix=None,
            query="",
            table_limit=10,
            column_limit=10,
        )
        self.assertIn("not implemented for oracle", result.limitation)

        inspector = MagicMock()
        factory.register(DatabaseEngine.ORACLE, inspector)
        self.assertIs(inspector, factory.for_engine(DatabaseEngine.ORACLE))


class OracleSchemaInspectorTests(unittest.TestCase):
    def _module(self, connection: _FakeConnection) -> types.ModuleType:
        module = types.ModuleType("oracledb")
        module.connect = MagicMock(return_value=connection)  # type: ignore[attr-defined]
        module.makedsn = MagicMock(return_value="safe-dsn")  # type: ignore[attr-defined]
        return module

    def test_uses_oracle_11g_catalog_queries_and_bounds_results(self) -> None:
        cursor = _ScriptedCursor(
            [
                [("GL001_EBR_ORDER",), ("GL001_EBR_ORDER_LINE",)],
                [
                    ("GL001_EBR_ORDER", "ORDER_NO", "VARCHAR2", "N"),
                    ("GL001_EBR_ORDER", "STATUS", "VARCHAR2", "Y"),
                    ("GL001_EBR_ORDER", "IGNORED", "NUMBER", "Y"),
                ],
            ]
        )
        connection = _FakeConnection(cursor)
        module = self._module(connection)

        with (
            patch.dict(sys.modules, {"oracledb": module}),
            patch(
                "app.modules.internal_api_platform.infrastructure.db.schema_directory."
                "assert_oracle_client_mode_ready"
            ),
        ):
            result = OracleSchemaInspector().read(
                _binding(DatabaseEngine.ORACLE, schema="app_owner"),
                table_prefix="GL001_EBR_",
                query="order",
                table_limit=1,
                column_limit=2,
            )

        self.assertTrue(result.truncated)
        self.assertEqual(["GL001_EBR_ORDER"], [table.name for table in result.tables])
        self.assertEqual(["ORDER_NO", "STATUS"], [c.name for c in result.tables[0].columns])
        self.assertFalse(result.tables[0].columns[0].nullable)
        self.assertTrue(result.tables[0].columns[1].nullable)

        table_sql, table_params = cursor.calls[0]
        self.assertIn("all_tables", table_sql.lower())
        self.assertIn("rownum", table_sql.lower())
        self.assertNotIn("fetch first", table_sql.lower())
        self.assertNotIn("offset", table_sql.lower())
        self.assertEqual("APP_OWNER", table_params["owner"])
        self.assertEqual("GL001\\_EBR\\_%", table_params["prefix"])
        self.assertEqual("%ORDER%", table_params["search"])
        self.assertEqual(2, table_params["row_limit"])

        column_sql, column_params = cursor.calls[1]
        self.assertIn("all_tab_columns", column_sql.lower())
        self.assertNotIn("GL001_EBR_ORDER", column_sql)
        self.assertEqual("GL001_EBR_ORDER", column_params["table_0"])
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)

    def test_rejects_invalid_owner_before_connecting(self) -> None:
        cursor = _ScriptedCursor([])
        connection = _FakeConnection(cursor)
        module = self._module(connection)
        with (
            patch.dict(sys.modules, {"oracledb": module}),
            patch(
                "app.modules.internal_api_platform.infrastructure.db.schema_directory."
                "assert_oracle_client_mode_ready"
            ),
            self.assertRaises(ResolutionError),
        ):
            OracleSchemaInspector().read(
                _binding(DatabaseEngine.ORACLE, schema="APP OWNER;DROP"),
                table_prefix=None,
                query="",
                table_limit=10,
                column_limit=10,
            )
        module.connect.assert_not_called()  # type: ignore[attr-defined]

    def test_connection_error_is_safe(self) -> None:
        module = types.ModuleType("oracledb")
        module.makedsn = MagicMock(return_value="safe-dsn")  # type: ignore[attr-defined]
        module.connect = MagicMock(  # type: ignore[attr-defined]
            side_effect=RuntimeError(
                "cannot connect private-db.internal reader top-secret-password"
            )
        )
        with (
            patch.dict(sys.modules, {"oracledb": module}),
            patch(
                "app.modules.internal_api_platform.infrastructure.db.schema_directory."
                "assert_oracle_client_mode_ready"
            ),
            self.assertRaises(UpstreamUnavailable) as raised,
        ):
            OracleSchemaInspector().read(
                _binding(DatabaseEngine.ORACLE),
                table_prefix=None,
                query="",
                table_limit=10,
                column_limit=10,
            )
        self.assertEqual("Oracle schema inspection connection failed", str(raised.exception))
        self.assertNotIn("private-db.internal", str(raised.exception))
        self.assertNotIn("top-secret-password", str(raised.exception))

    def test_metadata_query_error_is_safe_and_closes_resources(self) -> None:
        cursor = MagicMock()
        cursor.execute.side_effect = RuntimeError(
            "ORA-01031 private-db.internal top-secret-password"
        )
        connection = _FakeConnection(cursor)  # type: ignore[arg-type]
        module = self._module(connection)
        with (
            patch.dict(sys.modules, {"oracledb": module}),
            patch(
                "app.modules.internal_api_platform.infrastructure.db.schema_directory."
                "assert_oracle_client_mode_ready"
            ),
            self.assertRaises(UpstreamUnavailable) as raised,
        ):
            OracleSchemaInspector().read(
                _binding(DatabaseEngine.ORACLE),
                table_prefix=None,
                query="",
                table_limit=10,
                column_limit=10,
            )
        self.assertEqual("Oracle schema inspection query failed", str(raised.exception))
        self.assertNotIn("ORA-01031", str(raised.exception))
        cursor.close.assert_called_once()
        self.assertTrue(connection.closed)

    def test_missing_driver_is_explicit(self) -> None:
        with (
            patch.dict(sys.modules, {"oracledb": None}),
            patch(
                "app.modules.internal_api_platform.infrastructure.db.schema_directory."
                "assert_oracle_client_mode_ready"
            ),
            self.assertRaises(ResolutionError) as raised,
        ):
            OracleSchemaInspector().read(
                _binding(DatabaseEngine.ORACLE),
                table_prefix=None,
                query="",
                table_limit=10,
                column_limit=10,
            )
        self.assertEqual("Oracle driver is not installed", str(raised.exception))


class SqlServerSchemaInspectorTests(unittest.TestCase):
    def _module(self, connection: _FakeConnection) -> types.ModuleType:
        module = types.ModuleType("pymssql")
        module.connect = MagicMock(return_value=connection)  # type: ignore[attr-defined]
        return module

    def test_uses_sys_catalog_default_dbo_and_bounds_results(self) -> None:
        cursor = _ScriptedCursor(
            [
                [("GL001_EBR_order",), ("GL001_EBR_order_line",)],
                [
                    ("GL001_EBR_order", "order_no", "varchar", False),
                    ("GL001_EBR_order", "status", "varchar", True),
                    ("GL001_EBR_order", "ignored", "int", True),
                ],
            ]
        )
        connection = _FakeConnection(cursor)
        module = self._module(connection)

        with patch.dict(sys.modules, {"pymssql": module}):
            result = SqlServerSchemaInspector().read(
                _binding(DatabaseEngine.SQLSERVER),
                table_prefix="GL001_EBR_",
                query="order",
                table_limit=1,
                column_limit=2,
            )

        self.assertTrue(result.truncated)
        self.assertEqual(["GL001_EBR_order"], [table.name for table in result.tables])
        self.assertEqual(["order_no", "status"], [c.name for c in result.tables[0].columns])
        self.assertFalse(result.tables[0].columns[0].nullable)
        self.assertTrue(result.tables[0].columns[1].nullable)

        table_sql, table_params = cursor.calls[0]
        self.assertIn("sys.tables", table_sql.lower())
        self.assertIn("sys.schemas", table_sql.lower())
        self.assertIn("top (2)", table_sql.lower())
        self.assertEqual("dbo", table_params[0])
        self.assertEqual("GL001\\_EBR\\_%", table_params[1])
        self.assertEqual("%order%", table_params[2])

        column_sql, column_params = cursor.calls[1]
        self.assertIn("sys.columns", column_sql.lower())
        self.assertIn("sys.types", column_sql.lower())
        self.assertNotIn("GL001_EBR_order", column_sql)
        self.assertEqual(("dbo", "GL001_EBR_order"), column_params)
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)

    def test_uses_configured_schema(self) -> None:
        cursor = _ScriptedCursor([[], []])
        connection = _FakeConnection(cursor)
        module = self._module(connection)
        with patch.dict(sys.modules, {"pymssql": module}):
            result = SqlServerSchemaInspector().read(
                _binding(DatabaseEngine.SQLSERVER, schema="manufacturing"),
                table_prefix=None,
                query="order",
                table_limit=10,
                column_limit=10,
            )
        self.assertEqual([], result.tables)
        self.assertEqual("manufacturing", cursor.calls[0][1][0])
        self.assertEqual("%order%", cursor.calls[0][1][2])

    def test_connection_error_is_safe(self) -> None:
        module = types.ModuleType("pymssql")
        module.connect = MagicMock(  # type: ignore[attr-defined]
            side_effect=RuntimeError(
                "cannot connect private-db.internal reader top-secret-password"
            )
        )
        with (
            patch.dict(sys.modules, {"pymssql": module}),
            self.assertRaises(UpstreamUnavailable) as raised,
        ):
            SqlServerSchemaInspector().read(
                _binding(DatabaseEngine.SQLSERVER),
                table_prefix=None,
                query="",
                table_limit=10,
                column_limit=10,
            )
        self.assertEqual("SQL Server schema inspection connection failed", str(raised.exception))
        self.assertNotIn("private-db.internal", str(raised.exception))
        self.assertNotIn("top-secret-password", str(raised.exception))

    def test_metadata_query_error_is_safe_and_closes_resources(self) -> None:
        cursor = MagicMock()
        cursor.execute.side_effect = RuntimeError(
            "permission denied private-db.internal top-secret-password"
        )
        connection = _FakeConnection(cursor)  # type: ignore[arg-type]
        module = self._module(connection)
        with (
            patch.dict(sys.modules, {"pymssql": module}),
            self.assertRaises(UpstreamUnavailable) as raised,
        ):
            SqlServerSchemaInspector().read(
                _binding(DatabaseEngine.SQLSERVER),
                table_prefix=None,
                query="",
                table_limit=10,
                column_limit=10,
            )
        self.assertEqual("SQL Server schema inspection query failed", str(raised.exception))
        self.assertNotIn("permission denied", str(raised.exception))
        cursor.close.assert_called_once()
        self.assertTrue(connection.closed)

    def test_missing_driver_is_explicit(self) -> None:
        with (
            patch.dict(sys.modules, {"pymssql": None}),
            self.assertRaises(ResolutionError) as raised,
        ):
            SqlServerSchemaInspector().read(
                _binding(DatabaseEngine.SQLSERVER),
                table_prefix=None,
                query="",
                table_limit=10,
                column_limit=10,
            )
        self.assertEqual("SQL Server driver is not installed", str(raised.exception))


class MySqlSchemaInspectorContractTests(unittest.TestCase):
    def test_reads_only_information_schema(self) -> None:
        cursor = _ScriptedCursor(
            [[("GL001_EBR_order", "order_no", "varchar", "NO")]]
        )
        connection = _FakeConnection(cursor)
        module = types.ModuleType("pymysql")
        cursors = types.ModuleType("pymysql.cursors")
        cursors.Cursor = object  # type: ignore[attr-defined]
        module.cursors = cursors  # type: ignore[attr-defined]
        module.connect = MagicMock(return_value=connection)  # type: ignore[attr-defined]

        with patch.dict(sys.modules, {"pymysql": module, "pymysql.cursors": cursors}):
            result = MySqlSchemaInspector().read(
                _binding(DatabaseEngine.MYSQL),
                table_prefix="GL001_EBR_",
                query="order",
                table_limit=10,
                column_limit=10,
            )

        self.assertIsInstance(result, SchemaDirectory)
        self.assertEqual(["GL001_EBR_order"], [table.name for table in result.tables])
        sql = cursor.calls[0][0].lower()
        self.assertIn("information_schema.columns", sql)
        self.assertNotIn("gl001_ebr_order", sql)
        self.assertTrue(connection.closed)


class MultiDialectSchemaDirectoryServiceTests(unittest.TestCase):
    def _service(
        self,
        engine: DatabaseEngine,
        *,
        tables: list[SchemaTable],
    ) -> PlatformService:
        db = DatabaseConnection(
            host="private-db.internal",
            port=1521 if engine is DatabaseEngine.ORACLE else 1433,
            database="APPDB",
            user="reader",
            password="top-secret-password",
            schema="APP_OWNER" if engine is DatabaseEngine.ORACLE else "dbo",
            oracle_compat=OracleCompat.LEGACY,
        )
        base = Base(code="main", engine=engine, database=db)
        environment = Environment(code="prod", bases={"main": base})
        return PlatformService(
            registry=TopologyRegistry(Topology(environments={"prod": environment})),
            access_policy=AccessPolicy(
                scopes={"operator": AccessScope(rules=[ScopeRule()])}
            ),
            executors={engine: FakeQueryExecutor(rows=[{"status": "ok"}])},
            schema_inspector_factory=SchemaInspectorFactory(
                {engine: FakeSchemaInspector(tables=tables)}
            ),
            redis_gateway=FakeRedisGateway(),
            loki_client=FakeLokiClient(),
        )

    def test_api_contract_returns_bounded_oracle_and_sqlserver_metadata(self) -> None:
        for engine in (DatabaseEngine.ORACLE, DatabaseEngine.SQLSERVER):
            with self.subTest(engine=engine.value):
                service = self._service(
                    engine,
                    tables=[
                        SchemaTable("orders", [SchemaColumn("id", "number", False)]),
                        SchemaTable("order_lines", [SchemaColumn("id", "number", False)]),
                    ],
                )
                response = TestClient(create_app(service=service)).post(
                    "/tools/schema/directory",
                    json={
                        "environment": "prod",
                        "base": "main",
                        "query": "order",
                        "limit": 1,
                    },
                    headers={"x-agent-user-id": "operator"},
                )

                self.assertEqual(200, response.status_code)
                body = response.json()
                self.assertEqual(engine.value, body["summary"]["engine"])
                self.assertEqual(1, body["summary"]["table_count"])
                self.assertTrue(body["truncated"])
                self.assertEqual(
                    "internal-api-platform-schema", body["metadata"]["source"]
                )
                self.assertNotIn("private-db.internal", str(body))
                self.assertNotIn("top-secret-password", str(body))

    def test_api_contract_preserves_access_control(self) -> None:
        service = self._service(
            DatabaseEngine.SQLSERVER,
            tables=[SchemaTable("orders", [SchemaColumn("id", "int", False)])],
        )
        response = TestClient(create_app(service=service)).post(
            "/tools/schema/directory",
            json={"environment": "prod", "base": "main"},
            headers={"x-agent-user-id": "unauthorized"},
        )
        self.assertEqual(403, response.status_code)
        self.assertEqual("access_denied", response.json()["detail"]["error"]["code"])

    def test_query_validation_uses_schema_for_oracle_and_sqlserver(self) -> None:
        for engine in (DatabaseEngine.ORACLE, DatabaseEngine.SQLSERVER):
            with self.subTest(engine=engine.value):
                service = self._service(
                    engine,
                    tables=[SchemaTable("orders", [SchemaColumn("id", "number", False)])],
                )
                result = service.query_database(
                    user_id="operator",
                    environment="prod",
                    base="main",
                    workshop=None,
                    sql="select * from orders",
                )
                self.assertEqual(1, result.summary["row_count"])

                with self.assertRaises(PolicyViolation) as raised:
                    service.query_database(
                        user_id="operator",
                        environment="prod",
                        base="main",
                        workshop=None,
                        sql="select * from missing_table",
                    )
                self.assertEqual(
                    "stop_or_use_schema_directory",
                    raised.exception.diagnostic_action,
                )


if __name__ == "__main__":
    unittest.main()
