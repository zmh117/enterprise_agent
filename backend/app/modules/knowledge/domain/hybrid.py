"""混合检索版本合同；不是可由模型覆盖的搜索参数。"""

import math
from typing import Any

from app.modules.knowledge.domain.chunking import KEEP_IDS_PROFILE
from app.modules.knowledge.domain.vector_contract import VectorError


BM25_OPTIONS = {
    "tokenizer": "multilingual",
    "stemmer": {"type": "none"},
    "stopwords": {"custom": []},
    "lowercase": True,
    "k": 1.2,
    "b": 0.75,
    "avg_len": 256,
}
HYBRID_CONTRACT: dict[str, Any] = {
    "version": "ones-keep-ids-hybrid/v1",
    "sparse_model": "qdrant/bm25",
    "bm25_options": BM25_OPTIONS,
    "fusion": "rrf",
    "k": 2,
    "weights": [1.0, 1.0],
    "per_route_limit": 100,
}


def hybrid_index(index: dict[str, Any]) -> bool:
    return index.get("chunk_profile_hash") == KEEP_IDS_PROFILE.fingerprint


def lexical_input(index: dict[str, Any], row: dict[str, Any]) -> dict[str, str]:
    return {"lexical_text": row["embedding_text"]} if hybrid_index(index) else {}


def validate_sparse(vector: Any) -> None:
    if not isinstance(vector, dict) or set(vector) != {"indices", "values"}:
        raise VectorError("knowledge_sparse_vector_invalid")
    indices, values = vector["indices"], vector["values"]
    if (
        not isinstance(indices, list)
        or not isinstance(values, list)
        or not 1 <= len(indices) <= 8192
        or len(indices) != len(values)
        or any(type(i) is not int or not 0 <= i < 2**32 for i in indices)
        or len(set(indices)) != len(indices)
        or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in values)
    ):
        raise VectorError("knowledge_sparse_vector_invalid")
