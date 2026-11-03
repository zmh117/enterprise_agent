"""固定重排服务的有界协议；不加载模型、数据库或业务配置。"""

import math
from typing import Any

from app.modules.knowledge.domain.vector_contract import VectorError, fingerprint

MAX_CANDIDATE_POINTS = 200
MAX_DOCUMENTS = 50
MAX_BLOCKS = 2
MAX_BLOCK_CHARS = 1800
MAX_DOCUMENT_TOKENS = 1024
MAX_PAIR_TOKENS = 4096
MAX_BATCH_PAIRS = 8
MAX_BATCH_TOKENS = 8192
INFERENCE_THREADS = 8
MAX_BODY_BYTES = 1024 * 1024
RERANK_ENDPOINT = "http://knowledge-reranker:8097"
SAFE_ERRORS = frozenset(
    {
        "knowledge_rerank_busy",
        "knowledge_rerank_unavailable",
        "knowledge_rerank_read_timeout",
        "knowledge_rerank_input_limit",
        "knowledge_rerank_input_invalid",
        "knowledge_rerank_profile_mismatch",
        "knowledge_rerank_result_invalid",
    }
)


def checked_request(value: Any, profile_hash: str) -> tuple[str, list[list[str]]]:
    if (
        not isinstance(value, dict)
        or set(value) != {"profile_hash", "query", "documents"}
        or value["profile_hash"] != profile_hash
    ):
        raise VectorError("knowledge_rerank_input_invalid")
    query, documents = value["query"], value["documents"]
    if (
        not isinstance(query, str)
        or not query.strip()
        or len(query) > 2000
        or not isinstance(documents, list)
        or not 1 <= len(documents) <= MAX_DOCUMENTS
    ):
        raise VectorError("knowledge_rerank_input_invalid")
    for blocks in documents:
        if (
            not isinstance(blocks, list)
            or not 1 <= len(blocks) <= MAX_BLOCKS
            or any(
                not isinstance(block, str) or not block.strip() or len(block) > MAX_BLOCK_CHARS
                for block in blocks
            )
        ):
            raise VectorError("knowledge_rerank_input_invalid")
    try:
        query.encode("utf-8", errors="strict")
        for blocks in documents:
            for block in blocks:
                block.encode("utf-8", errors="strict")
    except UnicodeError:
        raise VectorError("knowledge_rerank_input_invalid") from None
    return query, documents


def input_hashes(query: str, documents: list[list[str]]) -> list[str]:
    return [fingerprint([query, blocks]) for blocks in documents]


def checked_result(
    value: Any, *, profile_hash: str, query: str, documents: list[list[str]]
) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != {"profile_hash", "input_hashes", "scores", "token_counts", "truncated"}
        or value["profile_hash"] != profile_hash
        or value["input_hashes"] != input_hashes(query, documents)
    ):
        raise VectorError("knowledge_rerank_result_invalid")
    for key in ("scores", "token_counts", "truncated"):
        if not isinstance(value[key], list) or len(value[key]) != len(documents):
            raise VectorError("knowledge_rerank_result_invalid")
    try:
        finite = all(type(s) in (float, int) and math.isfinite(s) for s in value["scores"])
    except OverflowError:
        finite = False
    if (
        not finite
        or any(type(n) is not int or not 1 <= n <= MAX_PAIR_TOKENS for n in value["token_counts"])
        or any(type(t) is not bool for t in value["truncated"])
    ):
        raise VectorError("knowledge_rerank_result_invalid")
    return value
