from __future__ import annotations

import re

from sqlglot import exp

from ..errors import PolicyViolation

_FORBIDDEN_FIRST_KEYWORDS = {"select", "with"}


def strip_sql_comments(sql: str) -> str:
    """Remove block and line comments so obfuscated statements cannot hide intent."""

    without_block = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    without_line = re.sub(r"--.*?$", " ", without_block, flags=re.M)
    without_hash = re.sub(r"#.*?$", " ", without_line, flags=re.M)
    return without_hash.strip()


def assert_first_keyword_readonly(sql: str) -> None:
    """Defense-in-depth check independent of the AST: the query must start read-only."""

    normalized = strip_sql_comments(sql).lower()
    first = normalized.split(None, 1)[0] if normalized else ""
    if first not in _FORBIDDEN_FIRST_KEYWORDS:
        raise PolicyViolation("Only read-only SELECT or WITH queries are allowed")


def assert_readonly_expression(expression: exp.Expression) -> None:
    """Reject any expression that is not a pure read-only query."""

    if not isinstance(expression, exp.Query):
        raise PolicyViolation("Only read-only SELECT or WITH queries are allowed")
    if list(expression.find_all(exp.Command)):
        raise PolicyViolation("Statement could not be parsed as a read-only query")
    if list(expression.find_all(exp.Into)):
        raise PolicyViolation("SELECT ... INTO is not allowed")
    if list(expression.find_all(exp.Lock)):
        raise PolicyViolation("Locking clauses such as FOR UPDATE are not allowed")
