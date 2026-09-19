"""稳定向量点身份与 payload；保持既有索引字节合同。"""

from collections.abc import Iterator
from typing import Any
import uuid


def batches(rows: Iterator[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    batch = []
    for row in rows:
        batch.append(row)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def point_id(index: dict[str, Any], row: dict[str, Any]) -> str:
    return str(uuid.uuid5(uuid.UUID(index["id"]), row["id"]))


def payload(index: dict[str, Any], row: dict[str, Any]) -> dict[str, str]:
    return {
        "index_id": index["id"],
        "knowledge_base_id": index["knowledge_base_id"],
        "document_id": row["document_id"],
        "revision_id": row["document_revision_id"],
        "chunk_id": row["id"],
        "profile_hash": index["profile_hash"],
        "embedding_hash": row["embedding_hash"],
        "chunk_kind": row["chunk_kind"],
    }
