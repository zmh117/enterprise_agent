"""读取随镜像打包的固定 Embedding profile。"""

import hashlib
import json
from pathlib import Path
from typing import Any
from app.modules.knowledge.domain.vector_contract import (
    DIMENSION,
    MAX_ITEMS,
    MAX_TOKENS,
    MAX_BATCH_TOKENS,
    fingerprint,
)

PACKAGE = Path(__file__).parents[1]
MODEL = json.loads((PACKAGE / "embedding_model.json").read_text())


def profile() -> dict[str, Any]:
    return {
        "contract": "knowledge-dense/v1",
        "model_id": MODEL["model_id"],
        "revision": MODEL["revision"],
        "artifact_hash": fingerprint(MODEL),
        "runtime_hash": hashlib.sha256(
            (PACKAGE / "embedding_runtime.lock").read_bytes()
        ).hexdigest(),
        "dimension": DIMENSION,
        "dtype": "float32",
        "normalize": True,
        "pooling": "official-sentence-transformers",
        "distance": "Cosine",
        "query_prefix": "",
        "max_items": MAX_ITEMS,
        "max_tokens": MAX_TOKENS,
        "max_batch_tokens": MAX_BATCH_TOKENS,
    }
