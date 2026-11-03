"""固定本地重排 profile；沿用经锁定的 CPU 推理依赖，不导入模型库。"""

import hashlib
import json
from typing import Any

from app.modules.knowledge.domain import rerank_contract as limits
from app.modules.knowledge.domain.vector_contract import fingerprint
from app.modules.knowledge.infrastructure.embedding_profile import PACKAGE, runtime_lock_path

MODEL = json.loads((PACKAGE / "reranker_model.json").read_text())


def profile() -> dict[str, Any]:
    return {
        "contract": "knowledge-reranker/v1",
        "model_id": MODEL["model_id"],
        "revision": MODEL["revision"],
        "artifact_hash": fingerprint(MODEL),
        "runtime_hash": hashlib.sha256(runtime_lock_path().read_bytes()).hexdigest(),
        "dtype": "float32",
        "device": "cpu",
        "threads": limits.INFERENCE_THREADS,
        "scoring": "sequence-classification-raw-logit",
        "window": "equal-block-prefix-redistribute/v1",
        "pair_template": "xlm-roberta-single-pair/v1",
        "batch_order": "token-length-desc-stable/v1",
        "tie_break": ["retrieval_score_desc", "document_id_asc"],
        "max_candidate_points": limits.MAX_CANDIDATE_POINTS,
        "max_documents": limits.MAX_DOCUMENTS,
        "max_blocks": limits.MAX_BLOCKS,
        "max_document_tokens": limits.MAX_DOCUMENT_TOKENS,
        "max_pair_tokens": limits.MAX_PAIR_TOKENS,
        "max_batch_pairs": limits.MAX_BATCH_PAIRS,
        "max_batch_tokens": limits.MAX_BATCH_TOKENS,
    }
