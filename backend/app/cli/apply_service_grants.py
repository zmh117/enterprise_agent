from __future__ import annotations

import os
from pathlib import Path

from psycopg import sql

from app.shared.config import load_settings
from app.shared.database import Database


_ROLE_PASSWORD_ENV = {
    "enterprise_agent_api": "API_DATABASE_PASSWORD",
    "enterprise_agent_worker": "WORKER_DATABASE_PASSWORD",
    "ones_mcp_reader": "ONES_MCP_DATABASE_PASSWORD",
    "data_mcp_runtime": "DATA_MCP_DATABASE_PASSWORD",
}


def apply_service_grants(database: Database, *, grants_path: Path) -> str:
    if database.engine != "postgres":
        return "skipped_non_postgres"

    passwords = {
        role: _required_password(environment_name)
        for role, environment_name in _ROLE_PASSWORD_ENV.items()
    }
    with database.unit_of_work():
        for role, password in passwords.items():
            existing = database.execute_one(
                "select rolname from pg_roles where rolname = ?",
                (role,),
            )
            statement = _role_password_statement(
                role=role,
                password=password,
                exists=existing is not None,
            )
            with database.session() as connection:
                cursor = connection.execute(statement)
                cursor.close()
        database.execute_script(
            grants_path.read_text(encoding="utf-8"),
            ignore_existing_errors=False,
        )
    return "applied"


def _role_password_statement(
    *,
    role: str,
    password: str,
    exists: bool,
) -> sql.Composed:
    operation = sql.SQL("ALTER ROLE") if exists else sql.SQL("CREATE ROLE")
    return sql.SQL("{} {} LOGIN PASSWORD {}").format(
        operation,
        sql.Identifier(role),
        sql.Literal(password),
    )


def _required_password(environment_name: str) -> str:
    value = os.getenv(environment_name, "")
    if len(value) < 16:
        raise RuntimeError(f"{environment_name} must contain at least 16 characters")
    return value


def main() -> int:
    database = Database(load_settings().database_dsn)
    grants_path = Path(__file__).resolve().parents[2] / "maintenance" / "mcp_service_grants.sql"
    try:
        status = apply_service_grants(database, grants_path=grants_path)
    except Exception:
        print("SERVICE_GRANTS_FAILED: roles or grants could not be applied")
        return 1
    finally:
        database.close()
    print(f"SERVICE_GRANTS_SUCCEEDED: status={status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
