from __future__ import annotations

import argparse
import os
import platform
import sys
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Protocol, cast

from .manifest import BASE_CODES, EXPECTED_ANOMALIES, EXPECTED_ROW_COUNTS, ROWS, TABLES, redis_fixtures

SENSITIVE_TOKENS = ("PASSWORD", "SECRET", "TOKEN", "KEY")


class Cursor(Protocol):
    def execute(self, sql: str, params: Any = None) -> Any: ...
    def fetchone(self) -> Any: ...
    def fetchall(self) -> Any: ...
    def close(self) -> Any: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...
    def commit(self) -> Any: ...
    def rollback(self) -> Any: ...
    def close(self) -> Any: ...


@dataclass(frozen=True)
class DataSourceResult:
    name: str
    ok: bool
    message: str


class AgentTestDataError(RuntimeError):
    pass


def mask(value: object) -> str:
    text = str(value)
    if not text:
        return ""
    if len(text) <= 4:
        return "****"
    return text[:2] + "…" + text[-2:]


def safe_error(exc: BaseException) -> str:
    text = str(exc)
    for key, value in os.environ.items():
        if any(token in key.upper() for token in SENSITIVE_TOKENS) and value:
            text = text.replace(value, mask(value))
    return text


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _env_int(name: str, default: int) -> int:
    value = _env(name)
    return int(value) if value else default


def _execute_many(cursor: Cursor, statements: Iterable[str]) -> None:
    for statement in statements:
        cursor.execute(statement)


class MySqlSeeder:
    name = "mysql"
    placeholder = "%s"

    def connect_admin(self) -> Connection:
        import pymysql

        return cast(Connection, pymysql.connect(
            host=_env("AGENT_TEST_MYSQL_HOST", "agent-test-mysql"),
            port=_env_int("AGENT_TEST_MYSQL_PORT", 3306),
            user=_env("AGENT_TEST_MYSQL_ADMIN_USER", "root"),
            password=_env("AGENT_TEST_MYSQL_ROOT_PASSWORD"),
            autocommit=False,
            charset="utf8mb4",
        ))

    def connect_reader(self) -> Connection:
        import pymysql

        return cast(Connection, pymysql.connect(
            host=_env("SECRET_AGENT_TEST_MYSQL_DB_HOST", "agent-test-mysql"),
            port=_env_int("SECRET_AGENT_TEST_MYSQL_DB_PORT", 3306),
            user=_env("SECRET_AGENT_TEST_MYSQL_DB_USER", "agent_test_reader"),
            password=_env("SECRET_AGENT_TEST_MYSQL_DB_PASSWORD"),
            database=_env("AGENT_TEST_MYSQL_DATABASE", "agent_test"),
            autocommit=False,
            charset="utf8mb4",
        ))

    def seed(self) -> None:
        conn = self.connect_admin()
        cur = conn.cursor()
        try:
            database = _env("AGENT_TEST_MYSQL_DATABASE", "agent_test")
            reader = _env("SECRET_AGENT_TEST_MYSQL_DB_USER", "agent_test_reader")
            reader_password = _env("SECRET_AGENT_TEST_MYSQL_DB_PASSWORD")
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4")
            cur.execute("CREATE USER IF NOT EXISTS %s@'%%' IDENTIFIED BY %s", (reader, reader_password))
            cur.execute(f"GRANT SELECT ON `{database}`.* TO %s@'%%'", (reader,))
            cur.execute(f"USE `{database}`")
            _execute_many(cur, mysql_schema_statements())
            _delete_fixture_rows(cur, self.placeholder)
            _insert_fixture_rows(cur, self.placeholder)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()

    def verify(self) -> None:
        _verify_database(self.connect_reader(), self.placeholder)


class SqlServerSeeder:
    name = "sqlserver"
    placeholder = "%s"

    def connect_admin(self, database: str = "master") -> Connection:
        import pymssql

        return cast(Connection, pymssql.connect(
            server=_env("AGENT_TEST_SQLSERVER_HOST", "agent-test-sqlserver"),
            port=str(_env_int("AGENT_TEST_SQLSERVER_PORT", 1433)),
            user=_env("AGENT_TEST_SQLSERVER_ADMIN_USER", "sa"),
            password=_env("AGENT_TEST_SQLSERVER_SA_PASSWORD"),
            database=database,
            login_timeout=10,
            timeout=30,
        ))

    def connect_reader(self) -> Connection:
        import pymssql

        return cast(Connection, pymssql.connect(
            server=_env("SECRET_AGENT_TEST_SQLSERVER_DB_HOST", "agent-test-sqlserver"),
            port=str(_env_int("SECRET_AGENT_TEST_SQLSERVER_DB_PORT", 1433)),
            user=_env("SECRET_AGENT_TEST_SQLSERVER_DB_USER", "agent_test_reader"),
            password=_env("SECRET_AGENT_TEST_SQLSERVER_DB_PASSWORD"),
            database=_env("AGENT_TEST_SQLSERVER_DATABASE", "agent_test"),
            login_timeout=10,
            timeout=30,
        ))

    def seed(self) -> None:
        database = _env("AGENT_TEST_SQLSERVER_DATABASE", "agent_test")
        reader = _env("SECRET_AGENT_TEST_SQLSERVER_DB_USER", "agent_test_reader")
        reader_password = _env("SECRET_AGENT_TEST_SQLSERVER_DB_PASSWORD")
        admin = self.connect_admin("master")
        cur = admin.cursor()
        try:
            cur.execute(f"IF DB_ID(%s) IS NULL CREATE DATABASE [{database}]", (database,))
            admin.commit()
            cur.execute(
                "IF SUSER_ID(%s) IS NULL "
                f"CREATE LOGIN [{reader}] WITH PASSWORD = %s, CHECK_POLICY = OFF",
                (reader, reader_password),
            )
            admin.commit()
        finally:
            cur.close()
            admin.close()

        conn = self.connect_admin(database)
        cur = conn.cursor()
        try:
            cur.execute(
                f"IF USER_ID(%s) IS NULL CREATE USER [{reader}] FOR LOGIN [{reader}]",
                (reader,),
            )
            _execute_many(cur, sqlserver_schema_statements())
            _delete_fixture_rows(cur, self.placeholder)
            _insert_fixture_rows(cur, self.placeholder)
            for table in TABLES:
                cur.execute(f"GRANT SELECT ON OBJECT::dbo.{table.name} TO [{reader}]")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()

    def verify(self) -> None:
        _verify_database(self.connect_reader(), self.placeholder)


class RedisSeeder:
    def __init__(self, base: str) -> None:
        self.base = base
        self.name = f"redis-{base}"

    def connect_admin(self) -> Any:
        import redis

        prefix = self.base.upper()
        return redis.Redis(
            host=_env(f"AGENT_TEST_REDIS_{prefix}_HOST", f"agent-test-redis-{self.base}"),
            port=_env_int(f"AGENT_TEST_REDIS_{prefix}_PORT", 6379),
            username=_env(f"AGENT_TEST_REDIS_{prefix}_ADMIN_USER", "default") or None,
            password=_env(f"AGENT_TEST_REDIS_{prefix}_ADMIN_PASSWORD") or None,
            socket_timeout=5,
            decode_responses=True,
        )

    def connect_reader(self) -> Any:
        import redis

        prefix = self.base.upper()
        return redis.Redis(
            host=_env(f"SECRET_AGENT_TEST_{prefix}_REDIS_HOST", f"agent-test-redis-{self.base}"),
            port=_env_int(f"SECRET_AGENT_TEST_{prefix}_REDIS_PORT", 6379),
            username=_env(f"SECRET_AGENT_TEST_{prefix}_REDIS_USER", "agent_test_reader"),
            password=_env(f"SECRET_AGENT_TEST_{prefix}_REDIS_PASSWORD"),
            socket_timeout=5,
            decode_responses=True,
        )

    def seed(self) -> None:
        client = self.connect_admin()
        prefix = self.base.upper()
        reader = _env(f"SECRET_AGENT_TEST_{prefix}_REDIS_USER", "agent_test_reader")
        reader_password = _env(f"SECRET_AGENT_TEST_{prefix}_REDIS_PASSWORD")
        seeder = _env(f"AGENT_TEST_REDIS_{prefix}_SEEDER_USER", "agent_test_seeder")
        seeder_password = _env(f"AGENT_TEST_REDIS_{prefix}_SEEDER_PASSWORD")
        pattern = f"agent_test:{self.base}:*"
        client.acl_setuser(
            reader,
            enabled=True,
            passwords=[f"+{reader_password}"],
            categories=["-@all"],
            commands=["+ping", "+get", "+scan"],
            keys=[pattern],
        )
        client.acl_setuser(
            seeder,
            enabled=True,
            passwords=[f"+{seeder_password}"],
            categories=["-@all"],
            commands=["+ping", "+get", "+set", "+del", "+scan", "+unlink"],
            keys=[pattern],
        )
        keys = list(client.scan_iter(match=pattern, count=100))
        if keys:
            client.delete(*keys)
        for item in redis_fixtures(self.base):
            client.set(item.key, item.value)

    def verify(self) -> None:
        client = self.connect_reader()
        expected_keys = {item.key: item.value for item in redis_fixtures(self.base)}
        found = list(client.scan_iter(match=f"agent_test:{self.base}:*", count=100))
        if set(found) != set(expected_keys):
            raise AgentTestDataError(
                f"Redis {self.base} keys mismatch expected={sorted(expected_keys)} got={sorted(found)}"
            )
        for key, value in expected_keys.items():
            if client.get(key) != value:
                raise AgentTestDataError(f"Redis {self.base} key {key} has unexpected value")
        try:
            client.set(f"agent_test:{self.base}:forbidden", "1")
        except Exception:
            return
        raise AgentTestDataError(f"Redis {self.base} reader unexpectedly allowed SET")


def mysql_schema_statements() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS production_order (
          order_no VARCHAR(64) PRIMARY KEY,
          product_code VARCHAR(64) NOT NULL,
          planned_qty INT NOT NULL,
          completed_qty INT NOT NULL,
          status VARCHAR(32) NOT NULL,
          planned_start_at DATETIME NOT NULL,
          planned_end_at DATETIME NOT NULL,
          actual_start_at DATETIME NULL,
          actual_end_at DATETIME NULL,
          updated_at DATETIME NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS equipment (
          equipment_code VARCHAR(64) PRIMARY KEY,
          equipment_name VARCHAR(128) NOT NULL,
          status VARCHAR(32) NOT NULL,
          last_heartbeat_at DATETIME NOT NULL,
          current_order_no VARCHAR(64) NULL,
          updated_at DATETIME NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS equipment_alarm (
          alarm_id VARCHAR(64) PRIMARY KEY,
          equipment_code VARCHAR(64) NOT NULL,
          severity VARCHAR(32) NOT NULL,
          alarm_code VARCHAR(64) NOT NULL,
          message VARCHAR(255) NOT NULL,
          occurred_at DATETIME NOT NULL,
          cleared_at DATETIME NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS material_inventory (
          inventory_id VARCHAR(64) PRIMARY KEY,
          material_code VARCHAR(64) NOT NULL,
          batch_no VARCHAR(64) NOT NULL,
          onhand_qty INT NOT NULL,
          reserved_qty INT NOT NULL,
          updated_at DATETIME NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS quality_inspection (
          inspection_id VARCHAR(64) PRIMARY KEY,
          order_no VARCHAR(64) NOT NULL,
          result VARCHAR(32) NOT NULL,
          defect_code VARCHAR(64) NULL,
          inspected_at DATETIME NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS production_event (
          event_id VARCHAR(64) PRIMARY KEY,
          order_no VARCHAR(64) NOT NULL,
          equipment_code VARCHAR(64) NOT NULL,
          event_type VARCHAR(64) NOT NULL,
          event_value VARCHAR(255) NOT NULL,
          occurred_at DATETIME NOT NULL
        )
        """,
    ]


def sqlserver_schema_statements() -> list[str]:
    return [
        """
        IF OBJECT_ID('dbo.production_order', 'U') IS NULL
        CREATE TABLE dbo.production_order (
          order_no NVARCHAR(64) NOT NULL PRIMARY KEY,
          product_code NVARCHAR(64) NOT NULL,
          planned_qty INT NOT NULL,
          completed_qty INT NOT NULL,
          status NVARCHAR(32) NOT NULL,
          planned_start_at DATETIME2 NOT NULL,
          planned_end_at DATETIME2 NOT NULL,
          actual_start_at DATETIME2 NULL,
          actual_end_at DATETIME2 NULL,
          updated_at DATETIME2 NOT NULL
        )
        """,
        """
        IF OBJECT_ID('dbo.equipment', 'U') IS NULL
        CREATE TABLE dbo.equipment (
          equipment_code NVARCHAR(64) NOT NULL PRIMARY KEY,
          equipment_name NVARCHAR(128) NOT NULL,
          status NVARCHAR(32) NOT NULL,
          last_heartbeat_at DATETIME2 NOT NULL,
          current_order_no NVARCHAR(64) NULL,
          updated_at DATETIME2 NOT NULL
        )
        """,
        """
        IF OBJECT_ID('dbo.equipment_alarm', 'U') IS NULL
        CREATE TABLE dbo.equipment_alarm (
          alarm_id NVARCHAR(64) NOT NULL PRIMARY KEY,
          equipment_code NVARCHAR(64) NOT NULL,
          severity NVARCHAR(32) NOT NULL,
          alarm_code NVARCHAR(64) NOT NULL,
          message NVARCHAR(255) NOT NULL,
          occurred_at DATETIME2 NOT NULL,
          cleared_at DATETIME2 NULL
        )
        """,
        """
        IF OBJECT_ID('dbo.material_inventory', 'U') IS NULL
        CREATE TABLE dbo.material_inventory (
          inventory_id NVARCHAR(64) NOT NULL PRIMARY KEY,
          material_code NVARCHAR(64) NOT NULL,
          batch_no NVARCHAR(64) NOT NULL,
          onhand_qty INT NOT NULL,
          reserved_qty INT NOT NULL,
          updated_at DATETIME2 NOT NULL
        )
        """,
        """
        IF OBJECT_ID('dbo.quality_inspection', 'U') IS NULL
        CREATE TABLE dbo.quality_inspection (
          inspection_id NVARCHAR(64) NOT NULL PRIMARY KEY,
          order_no NVARCHAR(64) NOT NULL,
          result NVARCHAR(32) NOT NULL,
          defect_code NVARCHAR(64) NULL,
          inspected_at DATETIME2 NOT NULL
        )
        """,
        """
        IF OBJECT_ID('dbo.production_event', 'U') IS NULL
        CREATE TABLE dbo.production_event (
          event_id NVARCHAR(64) NOT NULL PRIMARY KEY,
          order_no NVARCHAR(64) NOT NULL,
          equipment_code NVARCHAR(64) NOT NULL,
          event_type NVARCHAR(64) NOT NULL,
          event_value NVARCHAR(255) NOT NULL,
          occurred_at DATETIME2 NOT NULL
        )
        """,
    ]


def _delete_fixture_rows(cursor: Cursor, placeholder: str) -> None:
    for table in reversed(TABLES):
        ids = [row[table.primary_key] for row in ROWS[table.name]]
        marks = ", ".join(_placeholder(placeholder, index) for index, _ in enumerate(ids, start=1))
        cursor.execute(f"DELETE FROM {table.name} WHERE {table.primary_key} IN ({marks})", tuple(ids))


def _insert_fixture_rows(cursor: Cursor, placeholder: str) -> None:
    for table in TABLES:
        columns = ", ".join(table.columns)
        marks = ", ".join(_placeholder(placeholder, index) for index, _ in enumerate(table.columns, start=1))
        for row in ROWS[table.name]:
            values = tuple(row[column] for column in table.columns)
            cursor.execute(f"INSERT INTO {table.name} ({columns}) VALUES ({marks})", values)


def _placeholder(style: str, index: int) -> str:
    if style == ":{}":
        return f":{index}"
    return style


def _verify_database(conn: Connection, placeholder: str) -> None:
    cursor = conn.cursor()
    try:
        for table, count in EXPECTED_ROW_COUNTS.items():
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            actual = cursor.fetchone()[0]
            if int(actual) != count:
                raise AgentTestDataError(f"{table} row count expected {count}, got {actual}")
        cursor.execute(
            f"SELECT completed_qty FROM production_order WHERE order_no = {_placeholder(placeholder, 1)}",
            (EXPECTED_ANOMALIES["stuck_order"],),
        )
        completed = int(cursor.fetchone()[0])
        if completed != EXPECTED_ANOMALIES["stuck_order_db_completed_qty"]:
            raise AgentTestDataError("Stuck order sentinel mismatch")
        try:
            cursor.execute("INSERT INTO production_order (order_no) VALUES ('FORBIDDEN')")
        except Exception:
            return
        raise AgentTestDataError("Database reader unexpectedly allowed INSERT")
    finally:
        cursor.close()
        conn.close()


def run_sources(action: str, sources: list[Any] | None = None) -> list[DataSourceResult]:
    selected: list[Any] = (
        sources
        if sources is not None
        else [MySqlSeeder(), SqlServerSeeder()] + [RedisSeeder(base) for base in BASE_CODES]
    )
    results: list[DataSourceResult] = []
    for source in selected:
        try:
            getattr(source, action)()
        except Exception as exc:
            results.append(DataSourceResult(source.name, False, safe_error(exc)))
        else:
            results.append(DataSourceResult(source.name, True, "ok"))
    return results


def print_results(results: list[DataSourceResult]) -> int:
    failed = False
    for result in results:
        status = "ok" if result.ok else "failed"
        print(f"{result.name}: {status} - {result.message}")
        failed = failed or not result.ok
    return 1 if failed else 0


def warn_architecture(printer: Callable[[str], None] = print) -> None:
    machine = platform.machine().lower()
    if machine in {"arm64", "aarch64"}:
        printer(
            "WARNING: SQL Server Linux container runs as linux/amd64 on ARM64; "
            "this is a local test path and must pass health checks."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed or verify local agent test data")
    parser.add_argument("command", choices=("seed", "verify", "arch-check"))
    args = parser.parse_args(argv)
    if args.command == "arch-check":
        warn_architecture()
        return 0
    return print_results(run_sources(args.command))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
