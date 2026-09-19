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


class KnowledgeReadabilityClient:
    def __init__(
        self, identity: AccessTokenProvider, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.identity = identity
        self._transport = transport

    def check(self, *, token: str, request: ReadabilityRequest) -> dict[str, Any]:
        try:
            io_timeout(60)
            service_token = self.identity.access_token()
            budget = current_budget()
            assert_external_io_allowed("knowledge_readability_bridge")
            if self._transport is None:
                status, raw_body = request_bytes(
                    "POST",
                    "http://api-server:8000" + BRIDGE_PATH,
                    headers={
                        "Authorization": "Bearer " + service_token,
                        "X-Knowledge-Principal": "Bearer " + token,
                        "Content-Type": "application/json",
                        **(budget.headers() if budget is not None else {}),
                    },
                    content=json.dumps(asdict(request)).encode(),
                    timeout=io_timeout(60),
                    max_bytes=64 * 1024,
                )
                io_timeout(60)
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
                timeout=httpx.Timeout(io_timeout(60), connect=io_timeout(3)),
            ) as client:
                with client.stream(
                    "POST",
                    BRIDGE_PATH,
                    json=asdict(request),
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
                        io_timeout(60)
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
            io_timeout(60)
            raise KnowledgeGovernanceError("knowledge_readability_failed") from None
