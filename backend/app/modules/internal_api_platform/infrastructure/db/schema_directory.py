from __future__ import annotations

from ...domain.addressing import ResourceBinding
from ...domain.errors import ResolutionError
from ...domain.schema_directory import SchemaColumn, SchemaDirectory, SchemaTable
from ...domain.topology import DatabaseEngine


class UnsupportedSchemaDirectoryReader:
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


class FakeSchemaDirectoryReader:
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


class MySqlSchemaDirectoryReader:
    def read(
        self,
        binding: ResourceBinding,
        *,
        table_prefix: str | None,
        query: str,
        table_limit: int,
        column_limit: int,
    ) -> SchemaDirectory:
        if binding.database is None:
            raise ResolutionError("Base has no database connection configured")
        try:
            import pymysql
        except ModuleNotFoundError as exc:  # pragma: no cover - driver optional
            raise ResolutionError("MySQL driver is not installed") from exc
        db = binding.database
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
            for table_name, column_name, data_type, is_nullable in cur.fetchall():
                table = str(table_name)
                if query and query.lower() not in table.lower():
                    continue
                if len(tables.setdefault(table, [])) < column_limit:
                    tables[table].append(
                        SchemaColumn(
                            name=str(column_name),
                            data_type=str(data_type),
                            nullable=str(is_nullable).upper() == "YES",
                        )
                    )
            names = sorted(tables)
            truncated = len(names) > table_limit
            return SchemaDirectory(
                tables=[SchemaTable(name, tables[name]) for name in names[:table_limit]],
                truncated=truncated,
            )
        finally:
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
