from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from ...domain.addressing import ResourceBinding
from ...domain.errors import ResolutionError, UpstreamUnavailable
from ...domain.schema_directory import (
    SchemaColumn,
    SchemaDirectory,
    SchemaInspector,
    SchemaTable,
)
from ...domain.topology import DatabaseEngine, OracleClientMode
from .oracle_client import (
    assert_oracle_client_mode_ready,
    build_oracle_dsn,
    build_oracle_makedsn,
)


class SchemaInspectorFactory:
    def __init__(
        self,
        inspectors: Mapping[DatabaseEngine, SchemaInspector] | None = None,
    ) -> None:
        self._inspectors = dict(inspectors or {})

    def register(self, engine: DatabaseEngine, inspector: SchemaInspector) -> None:
        self._inspectors[engine] = inspector

    def for_engine(self, engine: DatabaseEngine) -> SchemaInspector:
        return self._inspectors.get(engine, UnsupportedSchemaInspector(engine))


class UnsupportedSchemaInspector:
    def __init__(self, engine: DatabaseEngine) -> None:
        self.engine = engine

    def read(
        self,
        binding: ResourceBinding,
        *,
        table_prefix: str | None,
        query: str,
        table_limit: int,
        column_limit: int,
    ) -> SchemaDirectory:
        return SchemaDirectory(
            tables=[],
            limitation=f"Schema directory is not implemented for {self.engine.value}",
        )


class FakeSchemaInspector:
    def __init__(self, tables: list[SchemaTable] | None = None) -> None:
        self.tables = (
            tables
            if tables is not None
            else [
                SchemaTable(
                    name="GL001_EBR_order",
                    columns=[
                        SchemaColumn("order_no", "varchar", False),
                        SchemaColumn("status", "varchar", True),
                    ],
                ),
                SchemaTable(
                    name="GL002_EBR_order",
                    columns=[
                        SchemaColumn("order_no", "varchar", False),
                        SchemaColumn("status", "varchar", True),
                    ],
                ),
            ]
        )
        self.calls: list[dict[str, object]] = []

    def read(
        self,
        binding: ResourceBinding,
        *,
        table_prefix: str | None,
        query: str,
        table_limit: int,
        column_limit: int,
    ) -> SchemaDirectory:
        self.calls.append(
            {
                "environment": binding.environment.code,
                "base": binding.base.code,
                "workshop": binding.workshop.code if binding.workshop else None,
                "query": query,
            }
        )
        tables = _filter_tables(self.tables, table_prefix=table_prefix, query=query)
        truncated = len(tables) > table_limit
        bounded = [
            SchemaTable(table.name, table.columns[:column_limit]) for table in tables[:table_limit]
        ]
        return SchemaDirectory(tables=bounded, truncated=truncated)


class MySqlSchemaInspector:
    def read(
        self,
        binding: ResourceBinding,
        *,
        table_prefix: str | None,
        query: str,
        table_limit: int,
        column_limit: int,
    ) -> SchemaDirectory:
        db = _require_database(binding)
        try:
            import pymysql
        except ModuleNotFoundError as exc:  # pragma: no cover - driver optional
            raise ResolutionError("MySQL driver is not installed") from exc
        try:
            conn = pymysql.connect(
                host=db.host,
                port=db.port,
                user=db.user,
                password=db.password,
                database=db.database or None,
                connect_timeout=5,
                read_timeout=5,
                cursorclass=pymysql.cursors.Cursor,
            )
        except Exception as exc:  # pragma: no cover - needs live DB
            raise UpstreamUnavailable("MySQL schema inspection connection failed") from exc
        cur: Any | None = None
        try:
            like_prefix = f"{table_prefix}%" if table_prefix else "%"
            cur = conn.cursor()
            cur.execute(
                """
                select table_name, column_name, data_type, is_nullable
                from information_schema.columns
                where table_schema = %s
                  and table_name like %s
                order by table_name, ordinal_position
                """,
                (db.database, like_prefix),
            )
            tables: dict[str, list[SchemaColumn]] = {}
            columns_truncated = False
            for table_name, column_name, data_type, is_nullable in cur.fetchall():
                table = str(table_name)
                if query and query.lower() not in table.lower():
                    continue
                columns = tables.setdefault(table, [])
                if len(columns) < column_limit:
                    columns.append(
                        SchemaColumn(str(column_name), str(data_type), str(is_nullable).upper() == "YES")
                    )
                else:
                    columns_truncated = True
            names = sorted(tables)
            truncated = len(names) > table_limit
            return SchemaDirectory(
                tables=[SchemaTable(name, tables[name]) for name in names[:table_limit]],
                truncated=truncated or columns_truncated,
            )
        except Exception as exc:  # pragma: no cover - needs live DB
            raise UpstreamUnavailable("MySQL schema inspection query failed") from exc
        finally:
            _close_quietly(cur)
            conn.close()


class OracleSchemaInspector:
    _identifier_pattern = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]{0,127}$")

    def read(
        self,
        binding: ResourceBinding,
        *,
        table_prefix: str | None,
        query: str,
        table_limit: int,
        column_limit: int,
    ) -> SchemaDirectory:
        db = _require_database(binding)
        mode = getattr(db, "oracle_client_mode", OracleClientMode.AUTO)
        assert_oracle_client_mode_ready(mode)
        try:
            import oracledb
        except ModuleNotFoundError as exc:  # pragma: no cover - driver optional
            raise ResolutionError("Oracle driver is not installed") from exc

        owner = self._owner(db.schema or db.user)
        dsn = (
            build_oracle_dsn(
                host=db.host,
                port=db.port,
                database=db.database,
                use_sid=bool(getattr(db, "use_sid", False)),
                connect_descriptor=str(getattr(db, "connect_descriptor", "") or ""),
            )
            if str(getattr(db, "connect_descriptor", "") or "").strip()
            else build_oracle_makedsn(
                oracledb,
                host=db.host,
                port=db.port,
                database=db.database,
                use_sid=bool(getattr(db, "use_sid", False)),
            )
        )
        try:
            conn = oracledb.connect(user=db.user, password=db.password, dsn=dsn)
            conn.call_timeout = 5000
        except Exception as exc:  # pragma: no cover - needs live DB
            raise UpstreamUnavailable("Oracle schema inspection connection failed") from exc

        cursor: Any | None = None
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT table_name
                FROM (
                    SELECT table_name
                    FROM all_tables
                    WHERE owner = :owner
                      AND table_name LIKE :prefix ESCAPE '\\'
                      AND table_name LIKE :search ESCAPE '\\'
                    ORDER BY table_name
                )
                WHERE ROWNUM <= :row_limit
                """,
                {
                    "owner": owner,
                    "prefix": _like_prefix(table_prefix, uppercase=True),
                    "search": _like_contains(query, uppercase=True),
                    "row_limit": table_limit + 1,
                },
            )
            raw_names = [str(row[0]) for row in cursor.fetchall()]
            names = _filter_table_names(raw_names, table_prefix=table_prefix, query=query)
            truncated = len(names) > table_limit
            selected = names[:table_limit]
            if not selected:
                return SchemaDirectory(tables=[], truncated=truncated)

            placeholders = ", ".join(f":table_{index}" for index in range(len(selected)))
            binds: dict[str, object] = {"owner": owner}
            binds.update({f"table_{index}": name for index, name in enumerate(selected)})
            cursor.execute(
                f"""
                SELECT table_name, column_name, data_type, nullable
                FROM all_tab_columns
                WHERE owner = :owner
                  AND table_name IN ({placeholders})
                ORDER BY table_name, column_id
                """,
                binds,
            )
            tables, columns_truncated = _tables_from_column_rows(
                selected,
                cursor.fetchall(),
                column_limit=column_limit,
                nullable=lambda value: str(value).upper() == "Y",
            )
            return SchemaDirectory(
                tables=tables,
                truncated=truncated or columns_truncated,
            )
        except Exception as exc:  # pragma: no cover - needs live DB
            raise UpstreamUnavailable("Oracle schema inspection query failed") from exc
        finally:
            _close_quietly(cursor)
            conn.close()

    def _owner(self, value: str) -> str:
        owner = str(value or "").strip()
        if not self._identifier_pattern.fullmatch(owner):
            raise ResolutionError("Oracle schema contains invalid characters")
        return owner.upper()


class SqlServerSchemaInspector:
    def read(
        self,
        binding: ResourceBinding,
        *,
        table_prefix: str | None,
        query: str,
        table_limit: int,
        column_limit: int,
    ) -> SchemaDirectory:
        db = _require_database(binding)
        try:
            import pymssql
        except ModuleNotFoundError as exc:  # pragma: no cover - driver optional
            raise ResolutionError("SQL Server driver is not installed") from exc
        try:
            conn = pymssql.connect(
                server=db.host,
                port=str(db.port),
                user=db.user,
                password=db.password,
                database=db.database or None,
                login_timeout=5,
                timeout=5,
            )
        except Exception as exc:  # pragma: no cover - needs live DB
            raise UpstreamUnavailable("SQL Server schema inspection connection failed") from exc

        cursor: Any | None = None
        try:
            cursor = conn.cursor()
            schema = str(db.schema or "").strip() or "dbo"
            row_limit = table_limit + 1
            cursor.execute(
                f"""
                SELECT TOP ({row_limit}) t.name
                FROM sys.tables AS t
                INNER JOIN sys.schemas AS s ON s.schema_id = t.schema_id
                WHERE s.name = %s
                  AND t.name LIKE %s ESCAPE '\\'
                  AND t.name LIKE %s ESCAPE '\\'
                ORDER BY t.name
                """,
                (
                    schema,
                    _like_prefix(table_prefix),
                    _like_contains(query),
                ),
            )
            raw_names = [str(row[0]) for row in cursor.fetchall()]
            names = _filter_table_names(raw_names, table_prefix=table_prefix, query=query)
            truncated = len(names) > table_limit
            selected = names[:table_limit]
            if not selected:
                return SchemaDirectory(tables=[], truncated=truncated)

            placeholders = ", ".join("%s" for _ in selected)
            cursor.execute(
                f"""
                SELECT t.name, c.name, ty.name, c.is_nullable
                FROM sys.tables AS t
                INNER JOIN sys.schemas AS s ON s.schema_id = t.schema_id
                INNER JOIN sys.columns AS c ON c.object_id = t.object_id
                INNER JOIN sys.types AS ty ON ty.user_type_id = c.user_type_id
                WHERE s.name = %s
                  AND t.name IN ({placeholders})
                ORDER BY t.name, c.column_id
                """,
                (schema, *selected),
            )
            tables, columns_truncated = _tables_from_column_rows(
                selected,
                cursor.fetchall(),
                column_limit=column_limit,
                nullable=bool,
            )
            return SchemaDirectory(
                tables=tables,
                truncated=truncated or columns_truncated,
            )
        except Exception as exc:  # pragma: no cover - needs live DB
            raise UpstreamUnavailable("SQL Server schema inspection query failed") from exc
        finally:
            _close_quietly(cursor)
            conn.close()


def _filter_tables(
    tables: list[SchemaTable], *, table_prefix: str | None, query: str
) -> list[SchemaTable]:
    lowered_query = query.lower().strip()
    result = []
    for table in tables:
        if table_prefix and not table.name.lower().startswith(table_prefix.lower()):
            continue
        if lowered_query and lowered_query not in table.name.lower():
            continue
        result.append(table)
    return result


def _require_database(binding: ResourceBinding) -> Any:
    if binding.database is None:
        raise ResolutionError("Base has no database connection configured")
    return binding.database


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _like_prefix(value: str | None, *, uppercase: bool = False) -> str:
    text = str(value or "")
    if uppercase:
        text = text.upper()
    return f"{_escape_like(text)}%"


def _like_contains(value: str, *, uppercase: bool = False) -> str:
    text = str(value or "").strip()
    if uppercase:
        text = text.upper()
    return f"%{_escape_like(text)}%"


def _filter_table_names(
    names: list[str], *, table_prefix: str | None, query: str
) -> list[str]:
    lowered_prefix = str(table_prefix or "").lower()
    lowered_query = str(query or "").strip().lower()
    return [
        name
        for name in names
        if (not lowered_prefix or name.lower().startswith(lowered_prefix))
        and (not lowered_query or lowered_query in name.lower())
    ]


def _tables_from_column_rows(
    table_names: list[str],
    rows: list[tuple[Any, ...]],
    *,
    column_limit: int,
    nullable: Callable[[Any], bool],
) -> tuple[list[SchemaTable], bool]:
    columns: dict[str, list[SchemaColumn]] = {name: [] for name in table_names}
    truncated = False
    folded_names = {name.lower(): name for name in table_names}
    for table_name, column_name, data_type, is_nullable, *_ in rows:
        actual_name = folded_names.get(str(table_name).lower())
        if actual_name is None:
            continue
        target = columns[actual_name]
        if len(target) >= column_limit:
            truncated = True
            continue
        target.append(
            SchemaColumn(
                name=str(column_name),
                data_type=str(data_type),
                nullable=bool(nullable(is_nullable)),
            )
        )
    return [SchemaTable(name, columns[name]) for name in table_names], truncated


def _close_quietly(resource: Any | None) -> None:
    if resource is None:
        return
    try:
        resource.close()
    except Exception:
        return


# Compatibility aliases for existing imports while callers migrate to inspector naming.
UnsupportedSchemaDirectoryReader = UnsupportedSchemaInspector
FakeSchemaDirectoryReader = FakeSchemaInspector
MySqlSchemaDirectoryReader = MySqlSchemaInspector
