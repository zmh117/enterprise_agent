from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def json_from_text(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value
