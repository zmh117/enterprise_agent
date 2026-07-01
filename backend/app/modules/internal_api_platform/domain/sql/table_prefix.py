from __future__ import annotations

from sqlglot import exp

from ..errors import PolicyViolation
from ..topology import DatabaseEngine
from .dialect import fold_identifier


def _cte_names(expression: exp.Expression) -> set[str]:
    return {cte.alias_or_name for cte in expression.find_all(exp.CTE)}


def extract_real_tables(expression: exp.Expression) -> list[str]:
    """Return physical table names referenced by the query, excluding CTE aliases."""

    ctes = _cte_names(expression)
    tables: list[str] = []
    for table in expression.find_all(exp.Table):
        name = table.name
        if not name or name in ctes:
            continue
        tables.append(name)
    return tables


def assert_workshop_prefix(
    expression: exp.Expression,
    *,
    table_prefix: str,
    engine: DatabaseEngine,
) -> list[str]:
    """Every physical table must belong to the workshop's table prefix.

    Comparison folds case per dialect so Oracle's unquoted upper-casing and general
    case-insensitive prefixes are handled. Returns the referenced table names.
    """

    tables = extract_real_tables(expression)
    if not tables:
        raise PolicyViolation("Query does not reference any table")
    folded_prefix = fold_identifier(table_prefix, engine)
    for name in tables:
        if not fold_identifier(name, engine).startswith(folded_prefix):
            raise PolicyViolation(
                f"Table '{name}' is outside the allowed workshop prefix '{table_prefix}'"
            )
    return tables
