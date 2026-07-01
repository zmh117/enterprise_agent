from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResponse:
    summary: dict[str, Any]
    raw: dict[str, Any] = field(default_factory=dict)
    truncated: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
