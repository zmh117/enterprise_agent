from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .addressing import ResourceBinding


@dataclass(frozen=True)
class SchemaColumn:
    name: str
    data_type: str
    nullable: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "data_type": self.data_type,
            "nullable": self.nullable,
        }


@dataclass(frozen=True)
class SchemaTable:
    name: str
    columns: list[SchemaColumn] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "columns": [column.to_dict() for column in self.columns],
        }


@dataclass(frozen=True)
class SchemaDirectory:
    tables: list[SchemaTable] = field(default_factory=list)
    truncated: bool = False
    limitation: str = ""

    def table_names(self) -> set[str]:
        return {table.name for table in self.tables}

    def table(self, name: str) -> SchemaTable | None:
        folded = name.lower()
        for table in self.tables:
            if table.name.lower() == folded:
                return table
        return None

    def to_summary(self) -> dict[str, Any]:
        return {
            "tables": [table.to_dict() for table in self.tables],
            "table_count": len(self.tables),
            "limitation": self.limitation,
        }


class SchemaDirectoryReader(Protocol):
    def read(
        self,
        binding: ResourceBinding,
        *,
        table_prefix: str | None,
        query: str,
        table_limit: int,
        column_limit: int,
    ) -> SchemaDirectory: ...
