"""单次知识调用读取当前票据，不改变身份或授权来源。"""

from collections.abc import Callable
from typing import Any

from app.modules.knowledge.domain.governance import KnowledgeGovernanceError

PRINCIPAL_REFRESH_PATH = "/api/internal/knowledge/principal/refresh"
PrincipalToken = str | Callable[[], str]


def current_principal(token: PrincipalToken) -> str:
    value = token() if callable(token) else token
    if not isinstance(value, str) or not value:
        raise KnowledgeGovernanceError("knowledge_principal_refresh_failed")
    return value


def stable_claims(claims: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in claims.items() if key not in {"jti", "iat", "nbf", "exp"}}
