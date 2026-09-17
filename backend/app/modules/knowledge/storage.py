"""离线导入与分块共用的存储原语；不创建 schema 或授予访问权。"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import threading
from typing import Any
import uuid

from app.modules.knowledge.ones_export import ExportValidationError, canonical_json
from app.shared.database import Database


TABLES = frozenset({
    "source", "document", "document_revision", "knowledge_base", "knowledge_base_document",
    "import_run", "document_relation", "document_chunk_set", "document_chunk",
})
_SQLITE_LOCK = threading.Lock()


def table(database: Database, name: str) -> str:
    if name not in TABLES:
        raise ValueError("Unknown knowledge table")
    return f'"knowledge.{name}"' if database.engine == "sqlite" else f"knowledge.{name}"


def stable_id(kind: str, *parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, canonical_json(["enterprise-agent-knowledge", kind, *parts])))


def now() -> str:
    return datetime.now(UTC).isoformat()


def insert(database: Database, name: str, values: dict[str, Any], *, conflict: str = "") -> None:
    database.execute(
        f"insert into {table(database, name)} ({', '.join(values)}) values ({', '.join('?' for _ in values)}) {conflict}",
        tuple(canonical_json(v) if isinstance(v, (dict, list)) else v for v in values.values()),
    )


@contextmanager
def source_lock(database: Database, source_id: str) -> Iterator[None]:
    with database.session():
        if database.engine == "postgres":
            key = int.from_bytes(hashlib.sha256(source_id.encode()).digest()[:8], "big", signed=True)
            result = database.execute_one("select pg_try_advisory_lock(?) as acquired", (key,))
            if not result or not result["acquired"]:
                raise ExportValidationError("knowledge_source_import_busy")
            try:
                yield
            finally:
                database.execute("select pg_advisory_unlock(?)", (key,))
        else:
            if not _SQLITE_LOCK.acquire(blocking=False):
                raise ExportValidationError("knowledge_source_import_busy")
            try:
                yield
            finally:
                _SQLITE_LOCK.release()
