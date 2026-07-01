from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LokiQuery:
    service: str
    query: str
    minutes: int
    limit: int
    logql: str


@dataclass
class LocalToolResult:
    summary: dict[str, Any]
    raw: dict[str, Any]
    metadata: dict[str, Any]
    truncated: bool
