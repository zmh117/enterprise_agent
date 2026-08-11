from __future__ import annotations

import os
from pathlib import Path

from psycopg import sql

from app.shared.config import load_settings
from app.shared.database import Database


ROLE = "agent_runtime_reader"
PASSWORD_ENV = "AGENT_RUNTIME_DATABASE_PASSWORD"


def apply_agent_runtime_grants(database: Database, *, grants_path: Path) -> str:
    if database.engine != "postgres":
        return "skipped_non_postgres"
    password = os.getenv(PASSWORD_ENV, "")
    if len(password) < 16:
        raise RuntimeError(f"{PASSWORD_ENV} must contain at least 16 characters")
    existing = database.execute_one(
        "select rolname from pg_roles where rolname = ?",
        (ROLE,),
    )
    operation = sql.SQL("ALTER ROLE") if existing is not None else sql.SQL("CREATE ROLE")
    statement = sql.SQL(
        "{} {} WITH LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE "
        "NOREPLICATION PASSWORD {}"
    ).format(operation, sql.Identifier(ROLE), sql.Literal(password))
    with database.unit_of_work():
        with database.session() as connection:
            cursor = connection.execute(statement)
            cursor.close()
        database.execute_script(
            grants_path.read_text(encoding="utf-8"),
            ignore_existing_errors=False,
        )
        verify_agent_runtime_grants(database)
    return "applied_and_verified"


def verify_agent_runtime_grants(database: Database) -> None:
    role = database.execute_one(
        """
        select rolsuper, rolinherit, rolcreaterole, rolcreatedb, rolreplication
          from pg_roles
         where rolname = ?
        """,
        (ROLE,),
    )
    if role is None or any(bool(value) for value in role.values()):
        raise RuntimeError("agent_runtime_reader role attributes are not least privilege")

    expected_columns = {
        "model_connection": {"id", "protocol", "status"},
        "model_connection_revision": {
            "id",
            "connection_id",
            "status",
            "config_json",
            "config_hash",
            "api_key_secret_id",
        },
        "platform_secret": {"id", "provider", "status", "active_version"},
        "platform_secret_version": {
            "secret_id",
            "version",
            "ciphertext",
            "nonce",
            "key_id",
            "algorithm",
            "status",
        },
    }
    for table, columns in expected_columns.items():
        for column in columns:
            allowed = database.execute_one(
                "select has_column_privilege(?, ?, ?, 'SELECT') as allowed",
                (ROLE, f"public.{table}", column),
            )
            if not allowed or not bool(allowed["allowed"]):
                raise RuntimeError(f"missing Agent Runtime SELECT grant: {table}.{column}")

    forbidden_tables = (
        "agent_job",
        "permission_policy",
        "audit_event",
        "agent_publication",
        "business_application_publication",
        "delivery_outbox",
    )
    for table in forbidden_tables:
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            row = database.execute_one(
                "select has_table_privilege(?, ?, ?) as allowed",
                (ROLE, f"public.{table}", privilege),
            )
            if row and bool(row["allowed"]):
                raise RuntimeError(
                    f"Agent Runtime has forbidden privilege: {table}.{privilege}"
                )

    for table in (
        "agent_runtime_terminal_ledger",
        "agent_runtime_invocation_claim",
        "agent_runtime_invocation_event",
    ):
        for privilege in ("SELECT", "INSERT", "DELETE"):
            row = database.execute_one(
                "select has_table_privilege(?, ?, ?) as allowed",
                (ROLE, f"public.{table}", privilege),
            )
            if not row or not bool(row["allowed"]):
                raise RuntimeError(
                    f"missing Agent Runtime ledger privilege: {table}.{privilege}"
                )
        row = database.execute_one(
            "select has_table_privilege(?, ?, 'UPDATE') as allowed",
            (ROLE, f"public.{table}"),
        )
        if row and bool(row["allowed"]):
            raise RuntimeError(f"Agent Runtime ledger UPDATE privilege is forbidden: {table}")


def main() -> int:
    database = Database(load_settings().database_dsn)
    grants_path = Path(__file__).resolve().parents[2] / "maintenance" / "agent_runtime_grants.sql"
    try:
        status = apply_agent_runtime_grants(database, grants_path=grants_path)
    except Exception:
        print("AGENT_RUNTIME_GRANTS_FAILED: role or privilege preflight failed")
        return 1
    finally:
        database.close()
    print(f"AGENT_RUNTIME_GRANTS_SUCCEEDED: status={status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
