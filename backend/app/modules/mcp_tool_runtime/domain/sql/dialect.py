from __future__ import annotations

from ..topology import DatabaseEngine

SQLGLOT_DIALECT: dict[DatabaseEngine, str] = {
    DatabaseEngine.MYSQL: "mysql",
    DatabaseEngine.SQLSERVER: "tsql",
    DatabaseEngine.ORACLE: "oracle",
}


def sqlglot_dialect(engine: DatabaseEngine) -> str:
    return SQLGLOT_DIALECT[engine]


def fold_identifier(name: str, engine: DatabaseEngine) -> str:
    """Fold an unquoted identifier to its effective stored form for comparison.

    Oracle folds unquoted identifiers to upper case; MySQL/SQL Server comparisons
    are treated case-insensitively here for prefix matching robustness.
    """

    return name.upper()
