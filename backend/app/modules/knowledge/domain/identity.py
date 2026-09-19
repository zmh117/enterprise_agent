"""现有稳定身份算法和时间表示。"""

from datetime import UTC, datetime
import uuid
from app.modules.knowledge.domain.normalization import canonical_json


def stable_id(kind: str, *parts: str) -> str:
    return str(
        uuid.uuid5(uuid.NAMESPACE_URL, canonical_json(["enterprise-agent-knowledge", kind, *parts]))
    )


def now() -> str:
    return datetime.now(UTC).isoformat()
