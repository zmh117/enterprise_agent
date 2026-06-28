from __future__ import annotations

import contextvars
import json
import logging
import sys
import uuid
from collections.abc import Callable
from typing import Any

correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default="-"
)


def new_correlation_id() -> str:
    return str(uuid.uuid4())


def set_correlation_id(value: str | None = None) -> str:
    correlation_id = value or new_correlation_id()
    correlation_id_var.set(correlation_id)
    return correlation_id


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": correlation_id_var.get(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def with_correlation(correlation_id: str | None, func: Callable[[], Any]) -> Any:
    token = correlation_id_var.set(correlation_id or new_correlation_id())
    try:
        return func()
    finally:
        correlation_id_var.reset(token)
