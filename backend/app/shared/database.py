from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any


class Database:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.engine = "sqlite" if dsn.startswith("sqlite://") else "postgres"
        self._connection: Any | None = None

    def connect(self) -> Any:
        if self._connection is not None:
            return self._connection
        if self.engine == "sqlite":
            path = self.dsn.removeprefix("sqlite:///")
            connection = sqlite3.connect(
                ":memory:" if path == ":memory:" else path,
                check_same_thread=False,
            )
            connection.row_factory = sqlite3.Row
            self._connection = connection
            return connection
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ModuleNotFoundError as exc:
            raise RuntimeError("psycopg is required for PostgreSQL connections") from exc
        self._connection = psycopg.connect(self.dsn, row_factory=dict_row)
        return self._connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def ping(self) -> bool:
        try:
            self.execute("select 1")
            return True
        except Exception:
            return False

    def execute(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        connection = self.connect()
        translated = self._translate_placeholders(sql)
        cursor = connection.execute(translated, tuple(params))
        rows = cursor.fetchall() if cursor.description else []
        connection.commit()
        return [dict(row) for row in rows]

    def execute_one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        rows = self.execute(sql, params)
        return rows[0] if rows else None

    def execute_script(self, script: str) -> None:
        connection = self.connect()
        if self.engine == "sqlite":
            for statement in self._split_statements(script):
                if self._is_postgres_comment_statement(statement):
                    continue
                try:
                    connection.execute(statement)
                    connection.commit()
                except Exception as exc:
                    if not self._is_ignorable_migration_error(exc):
                        raise
                    connection.rollback()
        else:
            for statement in self._split_statements(script):
                try:
                    connection.execute(statement)
                    connection.commit()
                except Exception as exc:
                    if not self._is_ignorable_migration_error(exc):
                        raise
                    connection.rollback()

    def run_migrations(self, migrations_dir: Path) -> None:
        for path in sorted(migrations_dir.glob("*.sql")):
            self.execute_script(path.read_text())

    def _translate_placeholders(self, sql: str) -> str:
        if self.engine == "postgres":
            return sql.replace("?", "%s")
        return sql

    def _split_statements(self, script: str) -> list[str]:
        return [statement.strip() for statement in script.split(";") if statement.strip()]

    def _is_ignorable_migration_error(self, exc: Exception) -> bool:
        message = str(exc).lower()
        return (
            "duplicate column" in message
            or "already exists" in message
            or "column" in message
            and "already" in message
        )

    def _is_postgres_comment_statement(self, statement: str) -> bool:
        return statement.lstrip().upper().startswith("COMMENT ON ")


def default_migrations_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "migrations"
