"""Knowledge MCP 到固定平台桥；不签发 Principal，也不持有 ONES 凭据。"""

from app.modules.knowledge.application.principal import PrincipalToken, current_principal

from dataclasses import asdict
import json
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.code_operation_errors import CODE_OPERATION_MESSAGES
from typing import Any

import httpx

from app.modules.identity.application.service_principal import AccessTokenProvider
from app.modules.knowledge.application.principal import PRINCIPAL_REFRESH_PATH
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError, strict_object
from app.modules.knowledge.application.readability import BRIDGE_PATH, ReadabilityRequest
from app.modules.knowledge.application.retrieval_budget import (
    MAX_RETRIEVAL_SECONDS,
    current_budget,
    io_timeout,
)
from app.shared.database import assert_external_io_allowed
from app.shared.bounded_read_http import request_bytes
from app.modules.knowledge.application.storage_broker import STORAGE_PATH
from app.shared.code_answer_tool_contracts import CODE_HISTORY_PATH


class KnowledgeReadabilityClient:
    def __init__(
        self, identity: AccessTokenProvider, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.identity = identity
        self._transport = transport

    def check(self, *, token: PrincipalToken, request: ReadabilityRequest) -> dict[str, Any]:
        io_timeout(MAX_RETRIEVAL_SECONDS)
        return self._post(token=token, path=BRIDGE_PATH, body=asdict(request))

    def connection(
        self, *, token: PrincipalToken, knowledge_base_id: str, revision_id: str
    ) -> dict[str, Any]:
        return self._post(
            token=token,
            path=STORAGE_PATH,
            body={"knowledge_base_id": knowledge_base_id, "resource_revision_id": revision_id},
        )

    def renew_principal(self, token: str) -> dict[str, Any]:
        return self._post(token=token, path=PRINCIPAL_REFRESH_PATH, body={})

    def code_history(self, *, token: PrincipalToken, request: dict[str, Any]) -> dict[str, Any]:
        return self._post(token=token, path=CODE_HISTORY_PATH, body=request)

    def _post(self, *, token: PrincipalToken, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if path not in {BRIDGE_PATH, STORAGE_PATH, PRINCIPAL_REFRESH_PATH, CODE_HISTORY_PATH}:
            raise KnowledgeGovernanceError("knowledge_input_invalid")
        try:
            io_timeout(MAX_RETRIEVAL_SECONDS)
            service_token = self.identity.access_token()
            budget = current_budget()
            assert_external_io_allowed("knowledge_readability_bridge")
            if self._transport is None:
                status, raw_body = request_bytes(
                    "POST",
                    "http://api-server:8000" + path,
                    headers={
                        "Authorization": "Bearer " + service_token,
                        "X-Knowledge-Principal": "Bearer " + current_principal(token),
                        "Content-Type": "application/json",
                        **(budget.headers() if budget is not None else {}),
                    },
                    content=json.dumps(body).encode(),
                    timeout=io_timeout(MAX_RETRIEVAL_SECONDS),
                    max_bytes=512 * 1024 if path == CODE_HISTORY_PATH else 64 * 1024,
                )
                io_timeout(MAX_RETRIEVAL_SECONDS)
                self._status(status, raw_body, path)
                value = json.loads(raw_body, object_pairs_hook=strict_object)
                if not isinstance(value, dict):
                    raise ValueError
                return value
            with httpx.Client(
                base_url="http://api-server:8000",
                transport=self._transport,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(io_timeout(MAX_RETRIEVAL_SECONDS), connect=io_timeout(3)),
            ) as client:
                with client.stream(
                    "POST",
                    path,
                    json=body,
                    headers={
                        "Authorization": "Bearer " + service_token,
                        "X-Knowledge-Principal": "Bearer " + current_principal(token),
                        **(budget.headers() if budget is not None else {}),
                    },
                ) as response:
                    raw = bytearray()
                    for part in response.iter_bytes():
                        io_timeout(MAX_RETRIEVAL_SECONDS)
                        raw.extend(part)
                        if len(raw) > (512 * 1024 if path == CODE_HISTORY_PATH else 64 * 1024):
                            raise ValueError
            self._status(response.status_code, bytes(raw), path)
            value = json.loads(raw, object_pairs_hook=strict_object)
            if not isinstance(value, dict):
                raise ValueError
            return value
        except (KnowledgeGovernanceError, CodeKnowledgeError):
            raise
        except Exception:
            io_timeout(MAX_RETRIEVAL_SECONDS)
            raise KnowledgeGovernanceError("knowledge_readability_failed") from None

    @staticmethod
    def _status(status: int, raw: bytes, path: str) -> None:
        if status == 200:
            return
        if path == CODE_HISTORY_PATH and status == 409:
            value = json.loads(raw, object_pairs_hook=strict_object)
            code = value.get("error_code") if isinstance(value, dict) else None
            if code in CODE_OPERATION_MESSAGES:
                raise CodeKnowledgeError(code)
        raise ValueError
