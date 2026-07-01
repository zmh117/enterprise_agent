from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ...domain.addressing import ResourceBinding


@dataclass
class ExecutedRows:
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False


class QueryExecutor(Protocol):
    def execute(
        self,
        binding: ResourceBinding,
        sql: str,
        *,
        timeout_seconds: int,
        max_rows: int,
    ) -> ExecutedRows: ...


class FakeQueryExecutor:
    """Deterministic executor for tests and local runs without a real database."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._rows = rows if rows is not None else [{"result": "ok"}]
        self.calls: list[tuple[str, str]] = []

    def execute(
        self,
        binding: ResourceBinding,
        sql: str,
        *,
        timeout_seconds: int,
        max_rows: int,
    ) -> ExecutedRows:
        self.calls.append((binding.engine.value, sql))
        rows = self._rows[:max_rows]
        truncated = len(self._rows) > max_rows
        columns = list(rows[0].keys()) if rows else []
        return ExecutedRows(columns=columns, rows=rows, truncated=truncated)
