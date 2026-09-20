"""Knowledge MCP 到固定平台桥；不签发 Principal，也不持有 ONES 凭据。"""

from dataclasses import asdict
import json
from typing import Any

import httpx

from app.modules.identity.application.service_principal import AccessTokenProvider
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError, strict_object
from app.modules.knowledge.application.readability import BRIDGE_PATH, ReadabilityRequest
from app.modules.knowledge.application.retrieval_budget import current_budget, io_timeout
from app.shared.database import assert_external_io_allowed
from app.shared.bounded_read_http import request_bytes
from app.modules.knowledge.application.storage_broker import STORAGE_PATH


class KnowledgeReadabilityClient:
    def __init__(
        self, identity: AccessTokenProvider, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.identity = identity
        self._transport = transport

    def check(self, *, token: str, request: ReadabilityRequest) -> dict[str, Any]:
        io_timeout(120)
        return self._post(token=token, path=BRIDGE_PATH, body=asdict(request))

    def connection(self, *, token: str, knowledge_base_id: str, revision_id: str) -> dict[str, Any]:
        return self._post(
            token=token,
            path=STORAGE_PATH,
            body={"knowledge_base_id": knowledge_base_id, "resource_revision_id": revision_id},
        )

    def _post(self, *, token: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if path not in {BRIDGE_PATH, STORAGE_PATH}:
            raise KnowledgeGovernanceError("knowledge_input_invalid")
        try:
            io_timeout(120)
            service_token = self.identity.access_token()
            budget = current_budget()
            assert_external_io_allowed("knowledge_readability_bridge")
            if self._transport is None:
                status, raw_body = request_bytes(
                    "POST",
                    "http://api-server:8000" + path,
                    headers={
                        "Authorization": "Bearer " + service_token,
                        "X-Knowledge-Principal": "Bearer " + token,
                        "Content-Type": "application/json",
                        **(budget.headers() if budget is not None else {}),
                    },
                    content=json.dumps(body).encode(),
                    timeout=io_timeout(120),
                    max_bytes=64 * 1024,
                )
                io_timeout(120)
                if status != 200:
                    raise ValueError
                value = json.loads(raw_body, object_pairs_hook=strict_object)
                if not isinstance(value, dict):
                    raise ValueError
                return value
            with httpx.Client(
                base_url="http://api-server:8000",
                transport=self._transport,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(io_timeout(120), connect=io_timeout(3)),
            ) as client:
                with client.stream(
                    "POST",
                    path,
                    json=body,
                    headers={
                        "Authorization": "Bearer " + service_token,
                        "X-Knowledge-Principal": "Bearer " + token,
                        **(budget.headers() if budget is not None else {}),
                    },
                ) as response:
                    if response.status_code != 200:
                        raise ValueError
                    raw = bytearray()
                    for part in response.iter_bytes():
                        io_timeout(120)
                        raw.extend(part)
                        if len(raw) > 64 * 1024:
                            raise ValueError
            value = json.loads(raw, object_pairs_hook=strict_object)
            if not isinstance(value, dict):
                raise ValueError
            return value
        except KnowledgeGovernanceError:
            raise
        except Exception:
            io_timeout(120)
            raise KnowledgeGovernanceError("knowledge_readability_failed") from None
