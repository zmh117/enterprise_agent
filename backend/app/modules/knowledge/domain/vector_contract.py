"""向量服务和平台客户端共用的纯数据合同，不加载模型或数据库。"""

import hashlib
import json
import math
from typing import Any

DIMENSION = 1024
MAX_ITEMS = 8
MAX_TOKENS = 4096
MAX_BATCH_TOKENS = 8192
MAX_BODY_BYTES = 256 * 1024


class VectorError(ValueError):
    """仅允许由本模块调用者提供固定机器错误码。"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def texts_from_request(value: Any, expected_profile: dict[str, Any]) -> list[str]:
    if not isinstance(value, dict) or set(value) != {"texts", "profile_hash"}:
        raise VectorError("knowledge_embedding_input_invalid")
    if value["profile_hash"] != fingerprint(expected_profile):
        raise VectorError("knowledge_embedding_profile_mismatch")
    texts = value["texts"]
    if (
        not isinstance(texts, list)
        or not 1 <= len(texts) <= MAX_ITEMS
        or any(not isinstance(t, str) or not t.strip() or len(t) > 20_000 for t in texts)
    ):
        raise VectorError("knowledge_embedding_input_invalid")
    return texts


def validate_vector(vector: Any) -> list[float]:
    if (
        not isinstance(vector, list)
        or len(vector) != DIMENSION
        or any(type(x) not in (int, float) or not math.isfinite(x) for x in vector)
    ):
        raise VectorError("knowledge_embedding_result_invalid")
    if not math.isclose(sum(x * x for x in vector), 1.0, rel_tol=1e-4, abs_tol=1e-4):
        raise VectorError("knowledge_embedding_result_invalid")
    return vector
