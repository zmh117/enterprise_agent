"""查询时文档重排；正文只用于固定模型输入，不进入返回引用。"""

from dataclasses import dataclass
import time
from typing import Any

from app.modules.knowledge.application.candidates import CandidatePool
from app.modules.knowledge.application.ports import RerankPort
from app.modules.knowledge.domain.rerank_contract import MAX_BLOCKS, checked_result


@dataclass(repr=False)
class RankedDocuments:
    documents: list[dict[str, Any]]
    profile_hash: str
    duration_ms: float
    truncated_documents: int


def rerank(pool: CandidatePool, query: str, client: RerankPort) -> RankedDocuments:
    documents = pool.selected
    if not documents:
        return RankedDocuments([], client.profile_hash, 0.0, 0)
    texts = [
        [pool.rows[e["chunk_id"]]["embedding_text"] for e in doc["evidence"][:MAX_BLOCKS]]
        for doc in documents
    ]
    started = time.monotonic()
    response = checked_result(
        client.rank(query, texts), profile_hash=client.profile_hash, query=query, documents=texts
    )
    scored = zip(documents, response["scores"], strict=True)
    ordered = sorted(
        scored, key=lambda pair: (-pair[1], -pair[0]["retrieval_score"], pair[0]["document_id"])
    )
    return RankedDocuments(
        [document for document, _ in ordered],
        client.profile_hash,
        (time.monotonic() - started) * 1000,
        sum(response["truncated"]),
    )
