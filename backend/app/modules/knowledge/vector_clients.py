"""固定内部地址的有界客户端，不记录请求正文或远端异常。"""

import json
import time
from typing import Any

import httpx

from app.modules.knowledge.vector_contract import (
    MAX_BATCH_TOKENS, MAX_ITEMS, MAX_TOKENS, VectorError, fingerprint, profile, validate_vector,
)
from app.shared.database import assert_external_io_allowed


class InternalHttp:
    def __init__(self, endpoint: str, *, transport: httpx.BaseTransport | None = None) -> None:
        if endpoint not in {"http://knowledge-embedding:8096", "http://knowledge-qdrant:6333"}:
            raise VectorError("knowledge_endpoint_invalid")
        self.client = httpx.Client(base_url=endpoint, transport=transport, trust_env=False,
                                   follow_redirects=False, timeout=httpx.Timeout(180, connect=5),
                                   limits=httpx.Limits(max_connections=2))

    def close(self) -> None:
        self.client.close()

    def request(self, method: str, path: str, value: Any = None, *, missing_ok: bool = False) -> Any:
        assert_external_io_allowed("knowledge_vector_http")
        for attempt in range(3):
            try:
                with self.client.stream(method, path, json=value) as response:
                    if response.status_code == 404 and missing_ok:
                        return None
                    if response.status_code >= 500:
                        raise httpx.TransportError("temporary")
                    if 300 <= response.status_code < 400:
                        raise VectorError("knowledge_vector_request_rejected")
                    data = bytearray()
                    for part in response.iter_bytes():
                        data.extend(part)
                        if len(data) > 2 * 1024 * 1024:
                            raise VectorError("knowledge_vector_response_limit")
                    value = json.loads(data)
                    if not isinstance(value, dict):
                        raise VectorError("knowledge_vector_response_invalid")
                    if not 200 <= response.status_code < 300:
                        # 只透传已定义的机器码，绝不回显远端消息、input 或 validation detail。
                        code = value.get("error_code")
                        safe_codes = {"knowledge_embedding_input_invalid", "knowledge_embedding_profile_mismatch",
                            "knowledge_embedding_token_limit", "knowledge_embedding_batch_limit",
                            "knowledge_embedding_body_limit", "knowledge_embedding_busy", "knowledge_embedding_read_timeout"}
                        raise VectorError(code if isinstance(code, str) and code in safe_codes
                                          else "knowledge_vector_request_rejected")
                    return value
            except httpx.TransportError:
                if attempt == 2:
                    raise VectorError("knowledge_vector_unavailable") from None
                time.sleep(2 ** attempt)
            except (ValueError, TypeError) as exc:
                if isinstance(exc, VectorError):
                    raise
                raise VectorError("knowledge_vector_response_invalid") from None
        raise VectorError("knowledge_vector_unavailable")


class EmbeddingClient:
    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self.http = InternalHttp("http://knowledge-embedding:8096", transport=transport)
        self.profile = profile()
        self.profile_hash = fingerprint(self.profile)

    def check(self) -> None:
        value = self.http.request("GET", "/profile")
        if value != {"profile": self.profile, "profile_hash": self.profile_hash}:
            raise VectorError("knowledge_embedding_profile_mismatch")

    def call(self, texts: list[str], *, encode: bool = False) -> dict[str, Any]:
        if not 1 <= len(texts) <= MAX_ITEMS:
            raise VectorError("knowledge_embedding_input_invalid")
        value = self.http.request("POST", "/embed" if encode else "/tokenize",
                                  {"texts": texts, "profile_hash": self.profile_hash})
        if (not isinstance(value, dict) or value.get("profile_hash") != self.profile_hash
                or value.get("input_hashes") != [fingerprint(t) for t in texts]):
            raise VectorError("knowledge_embedding_result_invalid")
        counts = value.get("token_counts")
        if (not isinstance(counts, list) or len(counts) != len(texts)
                or any(type(c) is not int or not 1 <= c <= MAX_TOKENS for c in counts)):
            raise VectorError("knowledge_embedding_result_invalid")
        if encode:
            vectors = value.get("vectors")
            if not isinstance(vectors, list) or len(vectors) != len(texts) or sum(counts) > MAX_BATCH_TOKENS:
                raise VectorError("knowledge_embedding_result_invalid")
            for vector in vectors:
                validate_vector(vector)
        return value


class QdrantClient:
    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self.http = InternalHttp("http://knowledge-qdrant:6333", transport=transport)

    @staticmethod
    def path(index: dict[str, Any]) -> str:
        # collection 不从任意输入拼接路径：仅由索引 UUID 派生。
        import uuid
        expected = "knowledge_" + uuid.UUID(index["id"]).hex
        if index["collection_name"] != expected:
            raise VectorError("knowledge_collection_conflict")
        return "/collections/" + expected

    def ensure(self, index: dict[str, Any]) -> None:
        self.check(index, create=True)
        path = self.path(index)
        for field in ("index_id", "knowledge_base_id"):
            self.http.request("PUT", path + "/index?wait=true", {"field_name": field, "field_schema": "keyword"})

    def check(self, index: dict[str, Any], *, create: bool = False) -> None:
        path = self.path(index)
        metadata = {"owner": "enterprise-agent-knowledge/v1", "index_id": index["id"],
                    "profile_hash": index["profile_hash"], "corpus_hash": index["corpus_hash"]}
        response = self.http.request("GET", path, missing_ok=True)
        if response is None and create:
            self.http.request("PUT", path, {"vectors": {"size": 1024, "distance": "Cosine"},
                                            "metadata": metadata})
            response = self.http.request("GET", path)
        if not isinstance(response, dict):
            raise VectorError("knowledge_collection_conflict")
        config = response.get("result", {}).get("config", {})
        vector = config.get("params", {}).get("vectors", {})
        if vector.get("size") != 1024 or vector.get("distance") != "Cosine" or config.get("metadata") != metadata:
            raise VectorError("knowledge_collection_conflict")

    def retrieve(self, index: dict[str, Any], ids: list[str]) -> dict[str, dict[str, Any]]:
        if not ids or len(ids) > 32:
            raise VectorError("knowledge_vector_batch_invalid")
        value = self.http.request("POST", self.path(index) + "/points",
                                  {"ids": ids, "with_payload": True, "with_vector": True})
        points = value.get("result")
        if not isinstance(points, list):
            raise VectorError("knowledge_vector_response_invalid")
        result: dict[str, dict[str, Any]] = {}
        for point in points:
            if not isinstance(point, dict) or point.get("id") not in ids or point["id"] in result:
                raise VectorError("knowledge_vector_response_invalid")
            validate_vector(point.get("vector"))
            result[point["id"]] = point
        return result

    def upsert(self, index: dict[str, Any], points: list[dict[str, Any]]) -> None:
        value = self.http.request("PUT", self.path(index) + "/points?wait=true", {"points": points})
        if value.get("result", {}).get("status") != "completed":
            raise VectorError("knowledge_vector_write_unconfirmed")

    def count(self, index: dict[str, Any]) -> int:
        value = self.http.request("POST", self.path(index) + "/points/count", {"exact": True})
        count = value.get("result", {}).get("count")
        if type(count) is not int or count < 0:
            raise VectorError("knowledge_vector_response_invalid")
        return count

    def search(self, index: dict[str, Any], vector: list[float], limit: int) -> list[dict[str, Any]]:
        value = self.http.request("POST", self.path(index) + "/points/query", {
            "query": vector, "limit": limit, "with_payload": True, "with_vector": False,
            "filter": {"must": [{"key": k, "match": {"value": v}} for k, v in
                                 (("index_id", index["id"]), ("knowledge_base_id", index["knowledge_base_id"]))]},
        })
        result = value.get("result", {}).get("points")
        if not isinstance(result, list) or len(result) > limit:
            raise VectorError("knowledge_vector_response_invalid")
        return result
