"""固定内网重排客户端；沿用受限 HTTP 与调用方原始截止时间。"""

from typing import Any
import httpx

from app.modules.knowledge.domain.rerank_contract import (
    RERANK_ENDPOINT,
    checked_request,
    checked_result,
)
from app.modules.knowledge.domain.vector_contract import VectorError, fingerprint
from app.modules.knowledge.infrastructure.reranker_profile import profile
from app.modules.knowledge.infrastructure.vector_clients import InternalHttp


class RerankerClient:
    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self.http = InternalHttp(RERANK_ENDPOINT, transport=transport)
        self.profile = profile()
        self.profile_hash = fingerprint(self.profile)

    def _request(self, method: str, path: str, value: Any = None) -> Any:
        try:
            return self.http.request(method, path, value)
        except VectorError as exc:
            if exc.code.startswith("knowledge_rerank_"):
                raise
            code = (
                "knowledge_rerank_read_timeout"
                if exc.code == "knowledge_vector_timeout"
                else "knowledge_rerank_unavailable"
            )
            raise VectorError(code) from None

    def check(self) -> None:
        observed = self._request("GET", "/profile")
        if observed != {"profile": self.profile, "profile_hash": self.profile_hash}:
            raise VectorError("knowledge_rerank_profile_mismatch")

    def rank(self, query: str, documents: list[list[str]]) -> dict[str, Any]:
        request = {"profile_hash": self.profile_hash, "query": query, "documents": documents}
        checked_request(request, self.profile_hash)
        self.check()
        return checked_result(
            self._request("POST", "/rerank", request),
            profile_hash=self.profile_hash,
            query=query,
            documents=documents,
        )
