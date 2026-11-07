"""离线导入与分块共用的存储原语；不创建 schema 或授予访问权。"""

from collections.abc import Iterator
from contextlib import contextmanager
import hashlib
import threading
from typing import Any

from app.modules.knowledge.domain.normalization import ExportValidationError, canonical_json
from app.shared.database import Database


TABLES = frozenset(
    {
        "code_checkout_job",
        "source",
        "document",
        "document_revision",
        "knowledge_base",
        "knowledge_base_document",
        "import_run",
        "document_relation",
        "document_chunk_set",
        "document_chunk",
        "vector_index",
        "vector_index_item",
        "source_binding",
        "retrieval_resource",
        "retrieval_revision",
        "retrieval_verification",
        "sync_binding",
        "sync_run",
        "sync_candidate",
        "ops_operation",
        "ops_event",
        "ops_runtime",
        "code_binding",
        "code_source_snapshot",
        "code_source_file",
        "code_commit",
        "code_build",
        "code_unit",
        "code_snapshot",
        "code_member",
        "code_relation",
        "code_dependency",
        "code_history_check",
        "code_demand",
        "code_object",
        "code_machine",
        "code_event",
        "code_state",
        "code_transition",
        "code_transition_source",
        "code_transition_failure",
    }
)
_SQLITE_LOCK = threading.RLock()


def table(database: Database, name: str) -> str:
    if name not in TABLES:
        raise ValueError("Unknown knowledge table")
    return f'"knowledge.{name}"' if database.engine == "sqlite" else f"knowledge.{name}"


def insert(database: Database, name: str, values: dict[str, Any], *, conflict: str = "") -> None:
    database.execute(
        f"insert into {table(database, name)} ({', '.join(values)}) values ({', '.join('?' for _ in values)}) {conflict}",
        tuple(canonical_json(v) if isinstance(v, (dict, list)) else v for v in values.values()),
    )


@contextmanager
def source_lock(database: Database, source_id: str) -> Iterator[None]:
    with database.session():
        if database.engine == "postgres":
            key = int.from_bytes(
                hashlib.sha256(source_id.encode()).digest()[:8], "big", signed=True
            )
            result = database.execute_one("select pg_try_advisory_lock(?) as acquired", (key,))
            if not result or not result["acquired"]:
                raise ExportValidationError("knowledge_source_import_busy")
            try:
                yield
            except BaseException:
                try:
                    database.execute("select pg_advisory_unlock(?)", (key,))
                except Exception:
                    # 会话销毁会释放锁，清理不能替换原始业务/数据库故障。
                    pass
                raise
            else:
                database.execute("select pg_advisory_unlock(?)", (key,))
        else:
            if not _SQLITE_LOCK.acquire(blocking=False):
                raise ExportValidationError("knowledge_source_import_busy")
            try:
                yield
            finally:
                _SQLITE_LOCK.release()
