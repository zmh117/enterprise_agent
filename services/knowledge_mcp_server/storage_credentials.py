"""单调用业务 Principal 上下文；连接凭据仅来自固定平台双身份入口。"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.infrastructure.readability_client import KnowledgeReadabilityClient


_TOKEN: ContextVar[str] = ContextVar("knowledge_storage_principal", default="")


@contextmanager
def storage_principal(token: str) -> Iterator[None]:
    handle = _TOKEN.set(token)
    try:
        yield
    finally:
        _TOKEN.reset(handle)


class BrokerStorageCredentials:
    def __init__(self, client: KnowledgeReadabilityClient) -> None:
        self.client = client

    def __call__(self, config: dict[str, Any], base_id: str, revision_id: str) -> dict[str, str]:
        token = _TOKEN.get()
        if not token or not base_id or not revision_id:
            raise KnowledgeGovernanceError("knowledge_job_denied")
        value = self.client.connection(
            token=token, knowledge_base_id=base_id, revision_id=revision_id
        )
        expected = {"postgres_password"} if config["postgres"]["mode"] == "external" else set()
        if config["qdrant"]["api_key_ref"]:
            expected.add("qdrant_api_key")
        credentials = value.get("credentials")
        if (
            set(value) != {"knowledge_base_id", "resource_revision_id", "config", "credentials"}
            or value["knowledge_base_id"] != base_id
            or value["resource_revision_id"] != revision_id
            or value["config"] != config
            or not isinstance(credentials, dict)
            or set(credentials) != expected
            or any(not isinstance(v, str) or not 1 <= len(v) <= 8192 for v in credentials.values())
        ):
            raise KnowledgeGovernanceError("knowledge_storage_credentials_unavailable")
        return credentials
