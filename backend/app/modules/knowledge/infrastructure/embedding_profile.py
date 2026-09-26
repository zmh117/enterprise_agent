"""读取随镜像打包的固定 Embedding profile。"""

import hashlib
import json
from pathlib import Path
import platform
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


def runtime_lock_path() -> Path:
    architecture = platform.machine().strip().lower()
    if architecture in {"arm64", "aarch64"}:
        return PACKAGE / "embedding_runtime.lock"
    if architecture in {"amd64", "x86_64"}:
        return PACKAGE / "embedding_runtime_amd64.lock"
    raise ValueError("Knowledge Embedding runtime architecture is not supported")


def profile() -> dict[str, Any]:
    return {
        "contract": "knowledge-dense/v1",
        "model_id": MODEL["model_id"],
        "revision": MODEL["revision"],
        "artifact_hash": fingerprint(MODEL),
        "runtime_hash": hashlib.sha256(runtime_lock_path().read_bytes()).hexdigest(),
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
