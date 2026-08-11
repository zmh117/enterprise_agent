from __future__ import annotations

import re

from sqlglot import exp

from ..errors import PolicyViolation
from ..topology import DatabaseEngine
from .dialect import fold_identifier


_PHYSICAL_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$#]*")


def _cte_names(
    expression: exp.Expression,
    *,
    engine: DatabaseEngine,
) -> set[str]:
    return {
        fold_identifier(cte.alias_or_name, engine)
        for cte in expression.find_all(exp.CTE)
        if cte.alias_or_name
    }


def extract_real_tables(
    expression: exp.Expression,
    *,
    engine: DatabaseEngine,
    allowed_database: str | None = None,
    allowed_schema: str | None = None,
) -> list[str]:
    """Return physical table names referenced by the query, excluding CTE aliases."""

    ctes = _cte_names(expression, engine=engine)
    tables: list[str] = []
    for table in expression.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise PolicyViolation("Dynamic or computed physical table references are not allowed")
        name = table.name
        if not name:
            raise PolicyViolation("Physical table name could not be determined")
        if fold_identifier(name, engine) in ctes and not table.db and not table.catalog:
            continue
        if _PHYSICAL_IDENTIFIER.fullmatch(name) is None:
            raise PolicyViolation("Physical table identifier contains unsafe characters")
        _assert_table_namespace(
            table,
            engine=engine,
            allowed_database=allowed_database,
            allowed_schema=allowed_schema,
        )
        if name not in tables:
            tables.append(name)
    if any(
        isinstance(node, (exp.Parameter, exp.Placeholder))
        for node in expression.walk()
        if isinstance(node.parent, exp.Table)
    ):
        raise PolicyViolation("Dynamic or parameterized physical table references are not allowed")
    return tables


def assert_workshop_prefix(
    expression: exp.Expression,
    *,
    table_prefix: str,
    engine: DatabaseEngine,
    allowed_database: str | None = None,
    allowed_schema: str | None = None,
) -> list[str]:
    """Every physical table must belong to the workshop's table prefix.

    Comparison folds case per dialect so Oracle's unquoted upper-casing and general
    case-insensitive prefixes are handled. Returns the referenced table names.
    """

    tables = extract_real_tables(
        expression,
        engine=engine,
        allowed_database=allowed_database,
        allowed_schema=allowed_schema,
    )
    if not tables:
        raise PolicyViolation("Query does not reference any table")
    folded_prefix = fold_identifier(table_prefix, engine)
    for name in tables:
        if not fold_identifier(name, engine).startswith(folded_prefix):
            raise PolicyViolation(
                f"Table '{name}' is outside the allowed workshop prefix '{table_prefix}'"
            )
    return tables


def _assert_table_namespace(
    table: exp.Table,
    *,
    engine: DatabaseEngine,
    allowed_database: str | None,
    allowed_schema: str | None,
) -> None:
    database = str(table.catalog or "")
    namespace = str(table.db or "")
    if database and engine is not DatabaseEngine.SQLSERVER:
        raise PolicyViolation("Cross-database physical table references are not allowed")
    if engine is DatabaseEngine.MYSQL:
        _assert_exact_qualifier(
            namespace,
            allowed_database,
            engine=engine,
            kind="database",
        )
        return
    if engine is DatabaseEngine.SQLSERVER:
        _assert_exact_qualifier(
            database,
            allowed_database,
            engine=engine,
            kind="database",
        )
        _assert_exact_qualifier(
            namespace,
            allowed_schema,
            engine=engine,
            kind="schema",
        )
        return
    _assert_exact_qualifier(
        namespace,
        allowed_schema,
        engine=engine,
        kind="schema",
    )


def _assert_exact_qualifier(
    actual: str,
    allowed: str | None,
    *,
    engine: DatabaseEngine,
    kind: str,
) -> None:
    if not actual:
        return
    if not allowed or fold_identifier(actual, engine) != fold_identifier(
        allowed,
        engine,
    ):
        raise PolicyViolation(f"Physical table {kind} qualifier is outside the frozen resource")
