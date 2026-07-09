from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from ..errors import PolicyViolation
from ..topology import DatabaseEngine, OracleCompat
from .dialect import sqlglot_dialect
from .readonly import (
    assert_first_keyword_readonly,
    assert_readonly_expression,
)
from .table_prefix import assert_workshop_prefix, extract_real_tables


@dataclass(frozen=True)
class AnalyzedQuery:
    sql: str
    tables: list[str] = field(default_factory=list)
    row_limit: int = 0


def _existing_limit(expression: exp.Expression) -> int | None:
    limit_node = expression.args.get("limit")
    if isinstance(limit_node, exp.Limit) and isinstance(limit_node.expression, exp.Literal):
        try:
            return int(limit_node.expression.name)
        except ValueError:
            return None
    return None


def _apply_oracle_legacy_rownum(sql: str, *, max_rows: int) -> str:
    """Wrap SQL with ROWNUM for older Oracle versions that lack FETCH FIRST."""

    stripped = sql.strip().rstrip(";")
    return f"SELECT * FROM ({stripped}) WHERE ROWNUM <= {max_rows}"


def analyze_readonly_query(
    sql: str,
    *,
    engine: DatabaseEngine,
    max_rows: int,
    table_prefix: str | None,
    oracle_compat: OracleCompat = OracleCompat.MODERN,
) -> AnalyzedQuery:
    """Validate and bound a read-only query, failing closed on any ambiguity.

    Order: comment-safe first-keyword check -> parse -> single-statement -> read-only
    AST -> workshop prefix (when partitioned) -> dialect-correct row limit.
    """

    assert_first_keyword_readonly(sql)
    dialect = sqlglot_dialect(engine)
    try:
        statements = [
            cast(exp.Expression, stmt)
            for stmt in sqlglot.parse(sql, read=dialect)
            if stmt is not None
        ]
    except SqlglotError as exc:
        raise PolicyViolation(f"Query could not be parsed safely: {exc}") from exc
    if len(statements) != 1:
        raise PolicyViolation("Exactly one SQL statement is allowed")

    expression = statements[0]
    assert_readonly_expression(expression)

    if table_prefix:
        tables = assert_workshop_prefix(expression, table_prefix=table_prefix, engine=engine)
    else:
        tables = extract_real_tables(expression)

    existing = _existing_limit(expression)
    effective = min(existing, max_rows) if existing is not None else max_rows
    if effective < 1:
        effective = 1

    if engine is DatabaseEngine.ORACLE and oracle_compat is OracleCompat.LEGACY:
        # Avoid FETCH FIRST (12c+); use ROWNUM wrapper for older servers.
        base_sql = expression.sql(dialect=dialect)
        return AnalyzedQuery(
            sql=_apply_oracle_legacy_rownum(base_sql, max_rows=effective),
            tables=tables,
            row_limit=effective,
        )

    query = cast(exp.Query, expression)
    bounded = query.limit(effective)
    return AnalyzedQuery(sql=bounded.sql(dialect=dialect), tables=tables, row_limit=effective)
